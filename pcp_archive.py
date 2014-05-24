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
    pmns = {}
    
    def _timestamp_to_datetime(self, tstamp):
        '''Convert a timestamp object (tv_sec + tv_usec) in a datetime
        object'''
        secs = tstamp.tv_sec + (tstamp.tv_usec * 10**-6)
        return datetime.fromtimestamp(secs)

    def _pmns_callback(self, label):
        '''Callback for the PMNS tree walk'''
        self.pmns[label] = None

    def __init__(self, pcp_fname, start=None, end=None):
        '''Opens a PCP archive and does an initial walk of the PMNS tree'''
        self.pcparchive = pcp_fname
        self.context = pmapi.pmContext(c_api.PM_CONTEXT_ARCHIVE, pcp_fname)
        self.context.pmTraversePMNS('', self._pmns_callback)
        self.start = start
        self.end = end

        # FIXME: right now I am using all PMIDs. This is because we
        # cannot be sure that a specific one always exists (??)
        # (Likely any pmid will do here)
        metrics = self.get_metrics()
        pmids = self.get_pmids(metrics)
        result = self.context.pmFetch(pmids)
        self.start_time = result.contents.timestamp
        self.end_time = self.context.pmGetArchiveEnd()

    def close(self):
        if self.context and self.result:
            self.context.pmFreeResult(self.result)

    def get_hostname(self):
        '''Returns the host that collected the metrics in the archive'''
        return self.context.pmGetContextHostName()

    def get_metrics(self):
        '''Returns a list of strings of the metrics contained
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

    def get_values(self, metrics):
        '''Given a single metric, returns a list of indoms containing
        (timestamp, value) tuples. If there are no indoms for the
        metric only a single list containing the (timestamp, value)
        tuples will be returnes. For example: [(ts1, 1.0), (ts2, 2.0)...]'''
        # Make sure we start at the beginning of the archive
        self.context.pmSetMode(c_api.PM_MODE_FORW, self.start_time, 0)
        temp_dict = {}
        while 1:
            pmids = self.context.pmLookupName(metrics)
            descs = self.context.pmLookupDescs(pmids)
            try:
                result = self.context.pmFetch(pmids)
            except pmapi.pmErr: # Archive is finished
                break

            dt = self._timestamp_to_datetime(result.contents.timestamp)
            if ((self.start and dt < self.start) or
                (self.end and dt > self.end)):
                self.context.pmFreeResult(result)
                continue

            # New dictionary for every timestamp
            temp_dict[dt] = {}
            for metric in range(len(descs)):
                count = result.contents.get_numval(metric)
                if count == 0: # No metric value present at this point in time
                    temp_dict[dt] = None
                    continue

                try:
                    (insts, nodes) = self.context.pmGetInDom(descs[metric]) 
                except:
                    insts = [0]
                    nodes = [0]
                val = {}
                # FIXME: this min() hack is because if the number of DOMs 
                # shrinks during the pmFetch loop pmGetIndom() still returns
                # the non shrinked size and we will segfault. Need to
                # investigate further
                for inst in range(min(len(insts), count)):
                    value = self.context.pmExtractValue(
                        result.contents.get_valfmt(metric),
                        result.contents.get_vlist(metric, inst),
                        descs[metric].contents.type, descs[metric].contents.type)

                    node = nodes[inst]
                    # FIXME: need to cater for all types
                    mtype = descs[metric].contents.type
                    if mtype == c_api.PM_TYPE_STRING:
                        val[node] = value.cp
                    elif mtype in [c_api.PM_TYPE_U64, c_api.PM_TYPE_64,
                                   c_api.PM_TYPE_U32, c_api.PM_TYPE_32]:
                        val[node] = value.ull
                    elif mtype == c_api.PM_TYPE_FLOAT:
                        val[node] = value.f
                    elif mtype == c_api.PM_TYPE_DOUBLE:
                        val[node] = value.d
                    else:
                        raise Exception("Metric has odd type: %s[%s]" % (
                                        metrics[metric], metric))
                    temp_dict[dt] = val
            self.context.pmFreeResult(result)

        if len(temp_dict) == 0:
            return {}

        # FIXME: make this cleaner and more pythonic
        # For users of this method it is simpler if the return data is in
        # the following form:
        # { 'indom1': [(ts0, ts1, ..., tsN), (val0, val1, ..., valN)],
        #   'indom2': [(ts0, ts1, ..., tsN), (val0, val1, ..., valN)],
        #   ....
        ret = {}
        for ts in sorted(temp_dict):
            tmp = temp_dict[ts]
            if tmp == None:
                continue
            for j in tmp:
                val = tmp[j]
                if j not in ret:
                    ret[j] = [(ts, val)]
                else:
                    ret[j].append((ts, val))

        for i in ret:
            ret[i] = zip(*ret[i])
            if len(ret[i][0]) != len(ret[i][1]):
                raise Exception("Error during parsing: {0}".format(ret[i]))

        # if ret[i][1] is all zeroes no need to create the graph
        # so return empty dict
        clean_ret = {key: value for key, value in ret.items() 
                     if not all([ v == 0 for v in value[1]])}

        return clean_ret
