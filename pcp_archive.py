# pcpstats - pcp(1) report graphing utility
# Copyright (C) 2014  Michele Baldessari
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.

from __future__ import print_function
from datetime import datetime

from pcp import pmapi
import cpmapi as c_api

class PcpHelp(object):
    '''Help texts are not shipped in an archive file. This class is used
    to fetch the help texts from the locally running pmcd service. This
    presumes that the PMNS tree is the same between the archive and the
    local PCP instance. Just a best effort thing. If the local PCP instance
    does not have the same PMDAs or has a different PMNS tree, texts
    will be missing'''
    pmns = {}
    help_text = {}
    context = None

    def _pmns_callback(self, label):
        '''Callback for the PMNS tree walk'''
        self.pmns[label] = None

    def __init__(self):
        try:
            self.context = pmapi.pmContext(target='local:')
        except:
            return
        self.context.pmTraversePMNS('', self._pmns_callback)
        for metric in self.pmns:
            try:
                pmid = self.context.pmLookupName(metric)
                text = self.context.pmLookupText(pmid[0])
                self.help_text[metric] = text
            except:
                pass

class PcpArchive(object):
    '''Class to make it easy to extract data from a PCP archive'''
    pcparchive = ''
    context = None
    result = None
    # keys is the metric string. Value is (type, sem, units)
    pmns = {}

    def __init__(self, pcp_fname, start=None, end=None):
        '''Opens a PCP archive and does an initial walk of the PMNS tree'''
        self.pcparchive = pcp_fname
        self.context = pmapi.pmContext(c_api.PM_CONTEXT_ARCHIVE, pcp_fname)
        self.context.pmTraversePMNS('', self._pmns_callback)
        self.start = start
        self.end = end

        tmp = self.context.pmGetArchiveLabel()
        self.start_time = tmp.start
        self.end_time = self.context.pmGetArchiveEnd()

    def _timestamp_to_datetime(self, tstamp):
        '''Convert a timestamp object (tv_sec + tv_usec) in a datetime
        object'''
        secs = tstamp.tv_sec + (tstamp.tv_usec * 10**-6)
        return datetime.fromtimestamp(secs)

    def _pmns_callback(self, label):
        '''Callback for the PMNS tree walk'''
        pmid = self.context.pmLookupName(label)
        desc = self.context.pmLookupDesc(pmid[0])
        self.pmns[label] = (desc.type, desc.sem, desc.contents.units)

    def _extract_value(self, result, desc, i, inst=0):
        '''Return python value given a pmExtractValue set of parameters'''
        mtype = desc.contents.type
        value = self.context.pmExtractValue(
            result.contents.get_valfmt(i),
            result.contents.get_vlist(i, inst),
            mtype, mtype)

        if mtype == c_api.PM_TYPE_U64:
            retval = value.ull
        elif mtype == c_api.PM_TYPE_U32:
            retval = value.ul
        elif mtype == c_api.PM_TYPE_64:
            retval = value.ll
        elif mtype == c_api.PM_TYPE_32:
            retval = value.l
        elif mtype == c_api.PM_TYPE_STRING:
            retval = value.cp
        elif mtype == c_api.PM_TYPE_FLOAT:
            retval = value.f
        elif mtype == c_api.PM_TYPE_DOUBLE:
            retval = value.d
        else:
            raise Exception("Metric has unknown type: [%s]" % (mtype))
        return retval

    def close(self):
        if self.context and self.result:
            self.context.pmFreeResult(self.result)

    def get_hostname(self):
        '''Returns the host that collected the metrics in the archive'''
        return self.context.pmGetContextHostName()

    def get_metrics(self):
        '''Returns a list of tuples of (metric, type) of all the metrics contained
        in the archive'''
        return self.pmns.keys()

    def get_pmids(self, metrics):
        '''Given a list of metrics, returns a list of PMIDs'''
        return self.context.pmLookupName(metrics)

    def get_timeinterval(self):
        '''Returns the a datetime tuple of the start and end of the
        archive'''
        # FIXME: need to use pmLocaltime here (??)
        d1 = self._timestamp_to_datetime(self.start_time)
        d2 = self._timestamp_to_datetime(self.end_time)
        return (d1, d2)

    def get_values(self, progress=None):
        '''Returns a dictionary of dictionary containing all the data within
        a PCP archive log file. Data will be returned as a a tuple
        (data, skipped_metrics). skipped_metrics is a list of metrics skipped
        because the archive log was corrupted. data will be in the following
        form:
        return[metric1] = {'indom1': [(ts0, ts1, .., tsN), (v0, v1, .., vN)],
                           ....
                           'indomN': [(ts0, ts1, .., tsN), (v0, v1, .., vN)]}
        return[metric2] = {'indom1': [(ts0, ts1, .., tsX), (v0, v1, .., vX)],
                           ....
                           'indomN': [(ts0, ts1, .., tsX), (v0, v1, .., vX)]}

        (ts0, .., tsN) are timestamps in datetime format and (v0, .., vN) are
        the actual values. If a metric has no indom 0 will be used as its key'''

        data = {}
        self.context.pmSetMode(c_api.PM_MODE_FORW, self.start_time, 0)
        skipped_metrics = []
        # This is just used as an optimization. The keys are (numpmid, numinst) and the value is
        # the indom name. This avoids too many expensive calls to pmNameInDomArchive
        indom_map = {}
        while 1:
            try:
                result = self.context.pmFetchArchive()
            except pmapi.pmErr, error:
                # Exit if we are at the end of the file or if the record is corrupted
                # Signal any other issues
                if error.args[0] in [c_api.PM_ERR_EOL, c_api.PM_ERR_LOGREC]:
                    break
                else:
                    raise error

            ts = self._timestamp_to_datetime(result.contents.timestamp)
            if ((self.start and ts < self.start) or
                (self.end and ts > self.end)):
                self.context.pmFreeResult(result)
                if progress:
                    progress(False)
                continue

            if progress:
                progress(True)
            for i in range(result.contents.numpmid):
                pmid = result.contents.get_pmid(i)
                desc = self.context.pmLookupDesc(pmid)
                metric = self.context.pmNameID(pmid)
                if metric not in data:
                    data[metric] = {}
                count = result.contents.get_numval(i)
                if count <= 1: # No indoms are present
                    try:
                        value = self._extract_value(result, desc, i)
                    except pmapi.pmErr, error:
                        if error.args[0] in [c_api.PM_ERR_CONV]:
                            skipped_metrics.append(metric)
                            continue
                        raise error
                    if 0 not in data[metric]:
                        data[metric][0] = [[ts,], [value,]]
                    else:
                        data[metric][0][0].append(ts)
                        data[metric][0][1].append(value)
                    continue

                for j in range(count):
                    inst = result.contents.get_inst(i, j)
                    try:
                        value = self._extract_value(result, desc, i, j)
                    except pmapi.pmErr, error:
                        if error.args[0] in [c_api.PM_ERR_CONV]:
                            skipped_metrics.append(metric)
                            continue
                    if (i, j) not in indom_map:
                        indom = self.context.pmNameInDomArchive(desc, inst)
                        indom_map[(i, j)] = indom
                    else:
                        indom = indom_map[(i, j)]
                    if indom not in data[metric]:
                        data[metric][indom] = [[ts,], [value,]]
                    else:
                        data[metric][indom][0].append(ts)
                        data[metric][indom][1].append(value)

            self.context.pmFreeResult(result)

        return (data, skipped_metrics)
