from pathlib import Path
import unittest
from unittest.mock import patch

from manette import monitor


class CpuTopologyTests(unittest.TestCase):
    def topology(self, ids, entries, cpuinfo=''):
        def read(path):
            path = Path(path)
            if str(path) == '/proc/cpuinfo':
                return cpuinfo
            return entries.get(int(path.parent.parent.name[3:]), {}).get(path.name, '')
        with patch.object(monitor, '_read', side_effect=read):
            return monitor.cpu_topology(ids)

    def test_smt_groups_non_adjacent_logical_processors(self):
        entries = {i: {'thread_siblings_list': f'{i % 6},{i % 6 + 6}'} for i in range(12)}
        topology = self.topology(tuple(range(12)), entries)
        self.assertEqual(topology.physical_count, 6)
        self.assertEqual(topology.groups, tuple((i, i + 6) for i in range(6)))

    def test_no_smt_does_not_halve_the_physical_core_count(self):
        entries = {i: {'physical_package_id': '0', 'core_id': str(i), 'core_cpus_list': str(i)}
                   for i in range(4)}
        topology = self.topology((0, 1, 2, 3), entries)
        self.assertEqual(topology.physical_count, 4)
        self.assertEqual(topology.groups, ((0,), (1,), (2,), (3,)))

    def test_hybrid_topology_allows_different_threads_per_core(self):
        entries = {i: {'physical_package_id': '0', 'core_id': str(i),
                       'core_cpus_list': '0,4' if i in (0, 4) else str(i)} for i in range(5)}
        topology = self.topology(tuple(range(5)), entries)
        self.assertEqual(topology.physical_count, 4)
        self.assertEqual(topology.groups, ((0, 4), (1,), (2,), (3,)))

    def test_core_ids_are_scoped_to_package_and_die(self):
        entries = {i: {'physical_package_id': str(i // 4), 'die_id': str((i // 2) % 2),
                       'core_id': '0'} for i in range(8)}
        topology = self.topology(tuple(range(8)), entries)
        self.assertEqual(topology.groups, ((0, 1), (2, 3), (4, 5), (6, 7)))

    def test_offline_siblings_are_not_shown_as_active_bars(self):
        entries = {i: {'thread_siblings_list': '0-3'} for i in (0, 3)}
        topology = self.topology((0, 3), entries)
        self.assertEqual(topology.groups, ((0, 3),))
        self.assertEqual(topology.physical_count, 1)

    def test_missing_and_kernel_default_topologies_remain_unknown(self):
        for entries in ({}, {i: {'physical_package_id': '-1', 'core_id': '0',
                                'thread_siblings_list': str(i)} for i in range(2)}):
            topology = self.topology((0, 1), entries)
            self.assertIsNone(topology.physical_count)
            self.assertFalse(topology.known)
            self.assertEqual(topology.groups, ((0,), (1,)))

    def test_inconsistent_sibling_claims_are_not_trusted(self):
        topology = self.topology((0, 1, 2), {0: {'thread_siblings_list': '0-1'},
            1: {'thread_siblings_list': '1-2'}, 2: {'thread_siblings_list': '1-2'}})
        self.assertFalse(topology.known)

    def test_proc_cpuinfo_fallback_requires_explicit_core_and_package_ids(self):
        text = 'processor : 0\nphysical id : 0\ncore id : 3\n\nprocessor : 4\nphysical id : 0\ncore id : 3'
        topology = self.topology((0, 4), {}, text)
        self.assertEqual(topology.groups, ((0, 4),))
        self.assertEqual(topology.physical_count, 1)
        incomplete = self.topology((0, 4), {}, 'processor : 0\ncpu cores : 1\nsiblings : 2')
        self.assertFalse(incomplete.known)

    def test_cpu_list_ranges_and_invalid_values(self):
        self.assertEqual(monitor._cpu_list('0-2,8,10-11'), {0, 1, 2, 8, 10, 11})
        for value in ('', '3-1', 'bad', '-1', '0-999999999', '0-1-2'):
            self.assertEqual(monitor._cpu_list(value), set())


class CpuSamplerTests(unittest.TestCase):
    def test_hotplug_does_not_assign_old_cpu_usage_to_a_different_cpu(self):
        readings = [
            'cpu 20 0 0 80\ncpu0 10 0 0 40\ncpu2 10 0 0 40\nintr 0',
            'cpu 40 0 0 100\ncpu0 20 0 0 50\ncpu3 100 0 0 0\nintr 0',
            'cpu 60 0 0 120\ncpu0 30 0 0 60\ncpu3 110 0 0 10\nintr 0',
        ]
        with patch.object(monitor, '_read', side_effect=readings), \
                patch.object(monitor, 'cpu_topology') as topology:
            sampler = monitor.CpuSampler()
            self.assertEqual(sampler.sample(), (0, [0, 0]))
            self.assertEqual(sampler.cpu_ids, (0, 2))
            self.assertEqual(sampler.sample(), (0.5, [0.5, 0]))
            self.assertEqual(sampler.cpu_ids, (0, 3))
            self.assertEqual(sampler.sample(), (0.5, [0.5, 0.5]))
            self.assertEqual(topology.call_count, 2)

    def test_missing_or_reset_counters_produce_zero_not_a_crash(self):
        with patch.object(monitor, '_read', side_effect=[
                'cpu 20 0 0 80\ncpu0 20 0 0 80',
                'cpu 1 0 0 1\ncpu0 1 0 0 1', '', 'cpu invalid\ncpu0 1']):
            with patch.object(monitor, 'cpu_topology'):
                sampler = monitor.CpuSampler()
                sampler.sample()
                self.assertEqual(sampler.sample(), (0, [0]))
                self.assertEqual(sampler.sample(), (0, []))
                self.assertEqual(sampler.sample(), (0, []))


if __name__ == '__main__':
    unittest.main()
