import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slurm_utils import resources


GPU_NODE = (
    "NodeName=gcn1 Arch=x86_64 CoresPerSocket=36 CPUAlloc=16 CPUTot=72 "
    "OS=Linux 5.14.0 #1 SMP Fri Sep 1 RealMemory=491520 AllocMem=122880 "
    "Gres=gpu:a100:4(S:0-1) GresUsed=gpu:a100:1(IDX:0) State=MIXED "
    "Partitions=gpu CfgTRES=cpu=72,mem=480G,billing=72,gres/gpu=4 "
    "AllocTRES=cpu=16,mem=120G,gres/gpu=1 Reason=(null)"
)
IDLE_GPU_NODE = (
    "NodeName=gcn2 CPUAlloc=0 CPUTot=72 RealMemory=491520 AllocMem=0 "
    "Gres=gpu:a100:4(S:0-1) GresUsed=gpu:a100:0 State=IDLE Partitions=gpu "
    "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES="
)
CPU_NODE = (
    "NodeName=tcn1 CPUAlloc=128 CPUTot=128 RealMemory=262144 AllocMem=262144 "
    "Gres=(null) State=ALLOCATED Partitions=cpu CfgTRES=cpu=128,mem=256G "
    "AllocTRES=cpu=128,mem=256G"
)
DOWN_NODE = (
    "NodeName=gcn3 CPUAlloc=0 CPUTot=72 RealMemory=491520 AllocMem=0 "
    "Gres=gpu:a100:4 GresUsed=gpu:a100:0 State=DOWN+DRAIN Partitions=gpu "
    "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES= Reason=hardware fault"
)


class ParsingTests(unittest.TestCase):
    def test_parse_node_record_keeps_multi_word_values(self):
        record = resources.parse_node_record(GPU_NODE)

        self.assertEqual(record["NodeName"], "gcn1")
        self.assertEqual(record["OS"], "Linux 5.14.0 #1 SMP Fri Sep 1")
        self.assertEqual(record["CfgTRES"], "cpu=72,mem=480G,billing=72,gres/gpu=4")

    def test_parse_tres_converts_memory_to_megabytes(self):
        tres = resources.parse_tres("cpu=72,mem=480G,billing=72,gres/gpu=4")

        self.assertEqual(tres["cpu"], 72)
        self.assertEqual(tres["mem"], 491520)
        self.assertEqual(tres["gres/gpu"], 4)

    def test_parse_gres_reads_type_and_count(self):
        self.assertEqual(resources.parse_gres("gpu:a100:4(S:0-1)"), ("a100", 4))
        self.assertEqual(resources.parse_gres("gpu:2"), (None, 2))
        self.assertEqual(resources.parse_gres("(null)"), (None, 0))

    def test_parse_jobs_keeps_separators_in_the_job_name(self):
        jobs = resources.parse_jobs(
            "4242|alice|RUNNING|1:02:03|2-00:00:00|16|120G|gres/gpu:2|a|b\n"
            "4243|bob|COMPLETING|0:05|1:00:00|8|32G|N/A|eval\n\n"
        )

        self.assertEqual([job["id"] for job in jobs], ["4242", "4243"])
        self.assertEqual(jobs[0]["name"], "a|b")
        self.assertEqual(jobs[0]["gres"], "gpu:2")
        self.assertEqual(jobs[1]["gres"], "")

    def test_build_node_reads_allocation(self):
        node = resources.parse_nodes(GPU_NODE)[0]

        self.assertEqual(node["gpu_type"], "a100")
        self.assertEqual((node["gpu_alloc"], node["gpu_total"]), (1, 4))
        self.assertEqual((node["cpu_alloc"], node["cpu_total"]), (16, 72))
        self.assertEqual((node["mem_alloc"], node["mem_total"]), (122880, 491520))
        self.assertTrue(node["available"])

    def test_build_node_falls_back_to_gres_used_without_alloc_tres(self):
        node = resources.parse_nodes(IDLE_GPU_NODE)[0]

        self.assertEqual(node["gpu_alloc"], 0)
        self.assertEqual(node["gpu_total"], 4)

    def test_down_node_is_unavailable(self):
        node = resources.parse_nodes(DOWN_NODE)[0]

        self.assertFalse(node["available"])
        self.assertEqual(node["reason"], "hardware fault")


class GroupingTests(unittest.TestCase):
    def test_gpu_partitions_come_before_cpu_only_partitions(self):
        nodes = resources.parse_nodes("\n".join([CPU_NODE, GPU_NODE]))

        groups = resources.group_nodes(nodes)

        self.assertEqual([key for key, _ in groups], [("gpu",), ("cpu",)])

    def test_nodes_in_a_partition_share_a_group_despite_small_memory_differences(self):
        other = GPU_NODE.replace("NodeName=gcn1", "NodeName=gcn9").replace(
            "RealMemory=491520", "RealMemory=491519"
        )
        nodes = resources.parse_nodes("\n".join([GPU_NODE, IDLE_GPU_NODE, other]))

        groups = resources.group_nodes(nodes)

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 3)
        self.assertEqual(resources.describe_hardware(groups[0][1]), "4x a100, 72 CPU, 480G RAM per node")

    def test_describe_hardware_lists_each_kind_in_a_mixed_partition(self):
        cpu = CPU_NODE.replace("Partitions=cpu", "Partitions=gpu")
        nodes = resources.parse_nodes("\n".join([GPU_NODE, IDLE_GPU_NODE, cpu]))

        description = resources.describe_hardware(nodes)

        self.assertIn("2x node with 4x a100", description)
        self.assertIn("1x node with no GPU", description)

    def test_classify(self):
        gpu, idle, cpu, down = resources.parse_nodes(
            "\n".join([GPU_NODE, IDLE_GPU_NODE, CPU_NODE, DOWN_NODE])
        )

        self.assertEqual(resources.classify(gpu), "partial")
        self.assertEqual(resources.classify(idle), "free")
        self.assertEqual(resources.classify(cpu), "full")
        self.assertEqual(resources.classify(down), "unavailable")

    def test_compress_hostlist(self):
        self.assertEqual(resources.compress_hostlist(["gcn1"]), "gcn1")
        self.assertEqual(
            resources.compress_hostlist(["gcn1", "gcn2", "gcn3", "gcn7"]), "gcn[1-3,7]"
        )
        self.assertEqual(resources.compress_hostlist(["gcn001", "gcn002"]), "gcn[001-002]")


class ReportTests(unittest.TestCase):
    def test_report_lists_availability_per_group(self):
        nodes = resources.parse_nodes(
            "\n".join([GPU_NODE, IDLE_GPU_NODE, CPU_NODE, DOWN_NODE])
        )

        report = resources.format_report(nodes)

        self.assertIn("partition: gpu  |  4x a100", report)
        self.assertIn("available: 7/8 GPUs", report)
        self.assertIn("free      gcn2", report)
        self.assertIn("partial   gcn1", report)
        self.assertIn("partition: cpu  |  no GPU", report)
        self.assertIn("down      gcn3", report)
        self.assertIn("hardware fault", report)
        self.assertIn("TOTAL available: 7/8 GPUs", report)

    def test_unavailable_nodes_do_not_count_as_free(self):
        nodes = resources.parse_nodes(DOWN_NODE)

        report = resources.format_report(nodes)

        self.assertIn("available: 0/0 GPUs", report)


if __name__ == "__main__":
    unittest.main()
