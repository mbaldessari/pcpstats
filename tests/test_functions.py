"""
Test unit for pcpstats
"""
from __future__ import print_function
import cProfile
import os
import os.path
import pstats
import resource
import StringIO
import sys
import tempfile
import time
import unittest

from pcp2pdf_archive import PcpArchive

# To debug memory leaks
USE_MELIAE = False
if USE_MELIAE:
    from meliae import scanner, loader
    import objgraph

# To profile speed
USE_PROFILER = True
TOP_PROFILED_FUNCTIONS = 15

PCP_FILES = 'pcp-files'


class TestPcpStats(unittest.TestCase):
    """Main UnitTest class"""
    def setUp(self):
        """Sets the test cases up"""
        if USE_PROFILER:
            self.profile = cProfile.Profile()
            self.profile.enable()
        self.start_time = time.time()

        pcp_base = os.path.join(sys.modules['tests'].__file__)
        print(pcp_base)
        self.pcp_dir = os.path.join(os.path.abspath(os.path.dirname(pcp_base)),
            PCP_FILES)
        tmp = []
        for root, dirs, files in os.walk(self.pcp_dir):
            for fname in files:
                if fname.lower().strip().endswith(".0"):
                    tmp.append(os.path.join(root, fname))

        self.pcp_files = sorted(tmp)

    def tearDown(self):
        """Called when the testrun is complete. Displays full time"""
        tdelta = time.time() - self.start_time
        print("{0}: {1:.5f}".format(self.id(), tdelta))

    def print_memusage(self, prefix=''):
        usage = resource.getrusage(resource.RUSAGE_SELF)
        print("{0}: usertime={1} systime={2} mem={3} MB"
            .format(prefix, usage[0], usage[1], (usage[2] / 1024.0)))

    def print_profiling(self, prefix=''):
        if not USE_PROFILER:
            return
        self.profile.disable()
        str_io = StringIO.StringIO()
        sortby = 'cumulative'
        pstat = pstats.Stats(self.profile, stream=str_io).sort_stats(sortby)
        pstat.print_stats(TOP_PROFILED_FUNCTIONS)
        print('{0}: {1}'.format(prefix, str_io.getvalue()))

    def print_leaks(self, prefix=''):
        if not USE_MELIAE:
            return
        objgraph.show_growth()
        tmp = tempfile.mkstemp(prefix='pcp-test')[1]
        scanner.dump_all_objects(tmp)
        leakreporter = loader.load(tmp)
        summary = leakreporter.summarize()
        print('{0}: {1}'.format(prefix, summary))

    def test_pcp(self):
        """Parses all the PCP archive files and creates the pdf outputs"""
        # Set up profiling for pdf generation
        if USE_PROFILER:
            self.profile.enable()

        for test_file in self.pcp_files:
            PcpArchive(test_file)
            fname = os.path.basename(test_file)
            self.print_memusage(prefix=fname)

if __name__ == '__main__':
    unittest.main()
