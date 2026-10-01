import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slurm_utils import resources, tui

NODES = resources.parse_nodes(
    "\n".join(
        [
            "NodeName=gcn1 CPUAlloc=16 CPUTot=72 RealMemory=491520 AllocMem=122880 "
            "Gres=gpu:a100:4 GresUsed=gpu:a100:1 State=MIXED Partitions=gpu "
            "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES=cpu=16,mem=120G,gres/gpu=1",
            "NodeName=gcn2 CPUAlloc=0 CPUTot=72 RealMemory=491520 AllocMem=0 "
            "Gres=gpu:a100:4 GresUsed=gpu:a100:0 State=IDLE Partitions=gpu "
            "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES=",
            "NodeName=gcn3 CPUAlloc=72 CPUTot=72 RealMemory=491520 AllocMem=491520 "
            "Gres=gpu:a100:4 GresUsed=gpu:a100:4 State=ALLOCATED Partitions=gpu "
            "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES=cpu=72,mem=480G,gres/gpu=4",
            "NodeName=gcn4 CPUAlloc=0 CPUTot=72 RealMemory=491520 AllocMem=0 "
            "Gres=gpu:a100:4 GresUsed=gpu:a100:0 State=IDLE+DRAIN Partitions=gpu "
            "CfgTRES=cpu=72,mem=480G,gres/gpu=4 AllocTRES= Reason=k8s cordon [root@2026-09-06T15:40:25]",
        ]
    )
)
FREE, PARTIAL, FULL, DOWN = NODES[1], NODES[0], NODES[2], NODES[3]


class BarTests(unittest.TestCase):
    def test_bar_scales_to_the_free_fraction(self):
        self.assertEqual(tui.bar(0, 8, 8), "░" * 8)
        self.assertEqual(tui.bar(8, 8, 8), "█" * 8)
        self.assertEqual(tui.bar(4, 8, 8), "████░░░░")

    def test_bar_handles_resourceless_nodes(self):
        self.assertEqual(tui.bar(0, 0, 4), "    ")
        self.assertEqual(tui.percent(0, 0), 0)


class SummaryTests(unittest.TestCase):
    def test_summarize_excludes_unavailable_nodes_from_free_totals(self):
        stats = tui.summarize(NODES)

        self.assertEqual(stats["nodes"], 4)
        self.assertEqual(stats["usable"], 3)
        self.assertEqual(stats["gpu_total"], 12)
        self.assertEqual(stats["gpu_free"], 7)
        self.assertEqual(stats["counts"]["unavailable"], 1)

    def test_group_label(self):
        (gpu_key, _), = [(key, nodes) for key, nodes in resources.group_nodes(NODES)]
        self.assertEqual(tui.group_label(gpu_key), "gpu")
        self.assertEqual(tui.group_label(("gpu", "debug")), "gpu,debug")
        self.assertEqual(tui.group_label(()), "no partition")

    def test_group_row_reports_free_counts_and_tally(self):
        key, nodes = resources.group_nodes(NODES)[0]

        text, detail, _ = tui.group_row(key, nodes)

        self.assertIn("gpu", text)
        self.assertIn("7/12", text)
        self.assertIn("1 free", text)
        self.assertIn("1 partial", text)
        self.assertIn("1 full", text)
        self.assertIn("1 down", text)
        self.assertEqual(detail, "4x a100, 72 CPU, 480G RAM per node")


class NodeRowTests(unittest.TestCase):
    def test_most_free_nodes_sort_first(self):
        order = [node["name"] for node in tui.sort_nodes(NODES)]

        self.assertEqual(order, ["gcn2", "gcn1", "gcn3", "gcn4"])

    def test_filter_by_bucket_and_search(self):
        self.assertEqual(
            [n["name"] for n in tui.filter_nodes(NODES, "partial")], ["gcn1"]
        )
        self.assertEqual(
            [n["name"] for n in tui.filter_nodes(NODES, None, "gcn3")], ["gcn3"]
        )
        self.assertEqual(tui.filter_nodes(NODES, "free", "gcn3"), [])

    def test_row_shows_free_resources(self):
        text, kind = tui.node_row(PARTIAL, show_gpu=True)

        self.assertEqual(kind, "partial")
        self.assertIn("3/4 GPU", text)
        self.assertIn("56/72 CPU", text)
        self.assertIn("360G/480G RAM", text)

    def test_row_for_unavailable_node_shows_state_and_reason_not_free_bars(self):
        text, kind = tui.node_row(DOWN, show_gpu=True)

        self.assertEqual(kind, "unavailable")
        self.assertIn("IDLE+DRAIN", text)
        self.assertIn("k8s cordon", text)
        self.assertNotIn("GPU", text)

    def test_row_omits_gpu_columns_for_cpu_only_groups(self):
        text, _ = tui.node_row(PARTIAL, show_gpu=False)

        self.assertNotIn("GPU", text)
        self.assertIn("56/72 CPU", text)


class DetailTests(unittest.TestCase):
    def test_detail_lists_every_resource(self):
        lines = "\n".join(tui.node_detail_lines(PARTIAL))

        self.assertIn("gcn1", lines)
        self.assertIn("MIXED", lines)
        self.assertIn("3 free of 4", lines)
        self.assertIn("56 free of 72", lines)
        self.assertIn("360G free of 480G", lines)

    def test_detail_includes_the_drain_reason(self):
        lines = "\n".join(tui.node_detail_lines(DOWN))

        self.assertIn("Reason", lines)
        self.assertIn("k8s cordon", lines)

    def test_detail_skips_the_null_reason(self):
        node = dict(FULL, reason="(null)")

        self.assertNotIn("Reason", "\n".join(tui.node_detail_lines(node)))


class JobLinesTests(unittest.TestCase):
    JOBS = resources.parse_jobs(
        "4242|alice|RUNNING|1:02:03|2-00:00:00|16|120G|gres/gpu:a100:1|train model\n"
        "4243_7|bob|RUNNING|0:05|1:00:00|8|32G|N/A|eval\n"
    )

    def test_table_has_a_header_and_one_row_per_job(self):
        lines = tui.job_lines(self.JOBS)

        self.assertEqual(lines[0], "Jobs (2)")
        self.assertTrue(lines[1].startswith("JOBID"))
        self.assertIn("alice", lines[2])
        self.assertIn("gpu:a100:1", lines[2])
        self.assertTrue(lines[2].endswith("train model"))
        self.assertTrue(lines[3].startswith("4243_7"))

    def test_columns_line_up(self):
        lines = tui.job_lines(self.JOBS)

        self.assertEqual(lines[1].index("USER"), lines[2].index("alice"))
        self.assertEqual(lines[2].index("alice"), lines[3].index("bob"))

    def test_empty_and_failed_job_lists(self):
        self.assertIn("no jobs", tui.job_lines([])[1])
        self.assertIn("timed out", tui.job_lines(None, "timed out")[1])


if __name__ == "__main__":
    unittest.main()
