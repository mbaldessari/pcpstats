#!/usr/bin/python
# pcp_stats - pcp(1) report graphing utility
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
from hashlib import sha1
from itertools import repeat
import multiprocessing
import os
import re
import resource
import shutil
import sys
import tempfile

from reportlab.platypus.paragraph import Paragraph
from reportlab.platypus import PageBreak, Image, Spacer, Table
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
import reportlab.lib.colors

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as colors
import matplotlib.cm as cm
#
# To debug memory leaks
USE_MELIAE = False
if USE_MELIAE:
    from meliae import scanner, loader
    import objgraph

from pcp_style import PcpDocTemplate
from pcp_archive import PcpArchive, PcpHelp

# If we should try and create the graphs in parallel
# brings a nice speedup on multi-core/smp machines
THREADED = True
# None means nr of available CPUs
NR_CPUS = None

# Inch graph size (width, height)
GRAPH_SIZE = (10.5, 6.5)
# Axis (title, fontsize, dateformat, locator in min)
X_AXIS = ('Time', 12, '%m-%d %H:%M', 20)

# Threshold above which the legend is placed on the bottom
# of the page
LEGEND_THRESHOLD = 50

def ellipsize(text, limit=100):
    '''Truncates a string in a nice-formatted way'''
    ret = text[:limit].rsplit(' ', 1)[0]
    if len(ret) > limit - 3:
        ret = ret + '...'
    return ret

def graph_wrapper((pcparch_obj, metric)):
    """This is a wrapper due to pool.map() single argument limit"""
    fname = pcparch_obj._graph_filename([metric])
    ret = pcparch_obj.create_graph(fname, metric, [metric])
    if ret:
        sys.stdout.write(".")
    else:
        sys.stdout.write("-")
    sys.stdout.flush()
    return (metric, ret)

def print_mem_usage(data):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    print("Graphing: {0} usertime={1} systime={2} mem={3} MB"
        .format(data, usage[0], usage[1],
        (usage[2] / 1024.0)))

class PcpStats(object):
    story = []

    def __init__(self, args, start_time=None, end_time=None, inc=None, exc=None):
        self.args = args
        self.pcphelp = PcpHelp()
        self.pcparchive = PcpArchive(args, start=start_time, end=end_time)
        # Using /var/tmp as /tmp is ram-mounted these days
        self.tempdir = tempfile.mkdtemp(prefix='pcpstats', dir='/var/tmp')
        # This contains all the metrics found in the archive file
        self.all_data = {}
        self.metrics = []
        if not inc and not exc:
            self.metrics = sorted(self.pcparchive.get_metrics())
        elif inc and not exc: # Only include filter specified
            metrics = sorted(self.pcparchive.get_metrics())
            for i in inc:
                try:
                    matched = filter(lambda x: re.match(i, x), metrics)
                except:
                    print("Failed to parse: {0}".format(i))
                    sys.exit(-1)
                self.metrics.extend(matched)
        elif not inc and exc: # Only exclude filter specified
            metrics = sorted(self.pcparchive.get_metrics())
            matched = []
            for i in exc:
                try:
                    matched.extend(filter(lambda x: re.match(i, x), metrics))
                except:
                    print("Failed to parse: {0}".format(i))
                    sys.exit(-1)

            self.metrics = sorted(list(set(metrics) - set(matched)))
        else:
            all_metrics = sorted(self.pcparchive.get_metrics())
            matched = []
            for i in exc:
                try:
                    matched.extend(filter(lambda x: re.match(i, x), all_metrics))
                except:
                    print("Failed to parse: {0}".format(i))
                    sys.exit(-1)

            delta_metrics = sorted(list(set(all_metrics) - set(matched)))
            metrics = sorted(self.pcparchive.get_metrics())
            for i in inc:
                try:
                    matched = filter(lambda x: re.match(i, x), metrics)
                except:
                    print("Failed to parse: {0}".format(i))
                    sys.exit(-1)
                delta_metrics.extend(matched)
            self.metrics = delta_metrics

        matplotlib.rcParams['figure.max_open_warning'] = 100

    def _graph_filename(self, metrics, extension='.png'):
        '''Creates a unique constant file name given a list of metrics'''
        temp = "_".join(metrics)
        digest = sha1()
        digest.update(temp)
        #fname = os.path.join(self.tempdir, digest.hexdigest() + extension)
        fname = os.path.join(self.tempdir, temp + extension)
        return fname

    def _do_heading(self, text, sty):
        # create bookmarkname
        bn = sha1(text + sty.name).hexdigest()
        # modify paragraph text to include an anchor point with name bn
        h = Paragraph(text + '<a name="%s"/>' % bn, sty)
        # store the bookmark name on the flowable so afterFlowable can see this
        h._bookmarkName = bn
        self.story.append(h)

    def parse(self):
        '''Parses the archive and stores all the metrics in self.all_data'''
        for metric in self.metrics:
            sys.stdout.write('.')
            sys.stdout.flush()
            self.all_data[metric] = self.pcparchive.get_values(metric)

    def is_string_metric(self, metric):
        '''Given a metric returns True if values' types are strings'''
        data = self.all_data[metric]
        isstring = False
        for indom in data:
            values = data[indom][1]
            if all([isinstance(v, str) for v in values]):
                isstring = True
                break
        return isstring

    def create_graph(self, fname, title, metrics):
        '''Take a title and a list of metrics and creates an image of
        the graph'''
        fig = plt.figure(figsize=(GRAPH_SIZE[0], GRAPH_SIZE[1]))
        axes = fig.add_subplot(111)
        # Set X Axis metadata
        axes.set_xlabel(X_AXIS[0])
        axes.set_title('{0} time series'.format(title, fontsize=X_AXIS[1]))
        axes.xaxis.set_major_formatter(mdates.DateFormatter(X_AXIS[2]))
        axes.xaxis.set_minor_locator(mdates.MinuteLocator(interval=X_AXIS[3]))
        fig.autofmt_xdate()

        # Set Y Axis metadata
        axes.set_ylabel(title)
        y_formatter = matplotlib.ticker.ScalarFormatter(useOffset=False)
        axes.yaxis.set_major_formatter(y_formatter)
        axes.yaxis.get_major_formatter().set_scientific(False)
        found = False
        indoms = 0
        for metric in metrics:
            values = self.all_data[metric]
            color_norm = colors.Normalize(vmin=0, vmax=len(values) - 1)
            scalar_map = cm.ScalarMappable(norm=color_norm,
                                           cmap=plt.get_cmap('Set1'))
            for counter, indom in enumerate(sorted(values)):
                (timestamps, dataset) = values[indom]
                # FIXME: currently if there is only one timestamp,value like with filesys.blocksize
                # we just do not graph the thing
                if len(timestamps) <= 1:
                    continue
                if indom == 0:
                    lbl = title
                else:
                    lbl = indom

                found = True
                try:
                    axes.plot(timestamps, dataset, 'o:', label=lbl,
                              color=scalar_map.to_rgba(counter))
                except:
                    import traceback
                    print("Metric: {0}".format(metric))
                    print(traceback.format_exc())
                    sys.exit(-1)

                indoms += 1

        if not found:
            return False
        axes.grid(True)

        # Add legend only when there is more than one instance
        lgd = False
        if indoms > 1:
            fontproperties = matplotlib.font_manager.FontProperties(size='xx-small')
            if indoms > LEGEND_THRESHOLD:
                # Draw legend on the bottom only when instances are more than LEGEND_THRESHOLD
                lgd = axes.legend(loc=9, ncol=int(indoms**0.6), bbox_to_anchor=(0.5, -0.29),
                                  shadow=True, prop=fontproperties)
            else:
                # Draw legend on the right when instances are more than LEGEND_THRESHOLD
                lgd = axes.legend(loc=1, ncol=int(indoms**0.5), shadow=True, prop=fontproperties)

        if lgd:
            plt.savefig(fname, bbox_extra_artists=(lgd,), bbox_inches='tight')
        else:
            plt.savefig(fname, bbox_inches='tight')
        plt.cla()
        plt.clf()
        plt.close('all')
        if USE_MELIAE:
            objgraph.show_growth()
            tmp = tempfile.mkstemp(prefix='pcp-test')[1]
            scanner.dump_all_objects(tmp)
            leakreporter = loader.load(tmp)
            summary = leakreporter.summarize()
            print(summary)
        return True

    def output(self, output_file='output.pdf'):
        sys.stdout.write('Parsing archive: ')
        sys.stdout.flush()
        self.parse()
        print()
        doc = PcpDocTemplate(output_file, pagesize=landscape(A4))
        hostname = self.pcparchive.get_hostname()
        self.story.append(Paragraph('%s' % hostname, doc.centered))
        self.story.append(Spacer(1, 0.05 * inch))
        self.story.append(Paragraph('%s' % (" ".join(self.args)),
                          doc.small_centered))
        self._do_heading('Table of contents', doc.centered_index)
        self.story.append(doc.toc)
        self.story.append(PageBreak())

        numeric_metrics = []
        string_metrics = []
        for metric in self.metrics:
            if self.is_string_metric(metric):
                string_metrics.append(metric)
            else:
                numeric_metrics.append(metric)

        done_metrics = []
        # This list contains the metrics that contained data
        print('Creating graphs: ', end='')
        if THREADED:
            pool = multiprocessing.Pool(NR_CPUS)
            l = zip(repeat(self), numeric_metrics)
            metrics_rets = pool.map(graph_wrapper, l)
            (metrics, rets) = zip(*metrics_rets)
            done_metrics = [metric for (metric, ret) in metrics_rets if ret]
        else:
            count = 0
            for metric in numeric_metrics:
                fname = self._graph_filename([metric])
                if self.create_graph(fname, metric, [metric]):
                    sys.stdout.write('.')
                    done_metrics.append(metric)
                else:
                    # Graphs had all zero values
                    sys.stdout.write('-')
                sys.stdout.flush()
                count += 1
                #if count > 70:
                #    break

        print()
        # At this point all images are created let's build the pdf
        count = 0
        print("Building pdf: ", end='')
        # Add with the lists of the string metrics
        data = [('Metric', 'Timestamp', 'Value')]
        for metric in string_metrics:
            last_value = None
            for indom in self.all_data[metric]:
                timestamps = self.all_data[metric][indom][0]
                values = self.all_data[metric][indom][1]
                for (ts, v) in zip(timestamps, values):
                    if last_value != v:
                        text = ellipsize(v)
                        data.append((metric, '%s' % ts, text))
                        last_value = v

        tablestyle = [ ('GRID', (0,0), (-1,-1), 1, reportlab.lib.colors.black),
                       ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                       ('LEFTPADDING', (0,0), (-1,-1), 3),
                       ('RIGHTPADDING', (0,0), (-1,-1), 3),
                       ('FONTSIZE', (0,0), (-1,-1), 10),
                       ('FONTNAME', (0,0), (-1,0), 'Times-Bold'), ]
        if len(data) > 1:
            self._do_heading('String metrics', doc.h1)
            self.story.append(Spacer(1, 0.2 * inch))
            table = Table(data)
            table.setStyle(tablestyle)
            self.story.append(table)
            self.story.append(PageBreak())
        # Add the graphs to the pdf
        last_category = ''
        for metric in done_metrics:
            # FIXME: this needs an appropriate method in pcp_archive
            category = metric.split('.')[0]
            if last_category != category:
                # FIXME: _do_heading should be moved in some other class/object/module
                self._do_heading(category, doc.h1)
                last_category = category

            fname = self._graph_filename([metric])
            self._do_heading(metric, doc.h2_invisible)
            self.story.append(Image(fname, width=GRAPH_SIZE[0]*inch,
                              height=GRAPH_SIZE[1]*inch))
            if metric in self.pcphelp.help_text:
                text = '<strong>%s</strong>: %s' % (metric,
                        self.pcphelp.help_text[metric])
                self.story.append(Paragraph(text, doc.normal))
            self.story.append(PageBreak())
            count += 1
            sys.stdout.write('.')
            sys.stdout.flush()
            #if count > 70:
            #    break

        doc.multiBuild(self.story)
        print()
        print("Done building: {0}".format(output_file))
        shutil.rmtree(self.tempdir)
        print("Done removing: {0}".format(self.tempdir))

    def print_info(self):
        # Print interval
        (start, end) = self.pcparchive.get_timeinterval()
        print('Interval: {0} - {1}'.format(start, end))
        # Print the metrics
        d = {}
        for metric in self.metrics:
            (prefix, metric) = metric.split('.', 1)
            if prefix in d:
                d[prefix].append(metric)
            else:
                d[prefix] = []

        try:
            rows, columns = os.popen('stty size', 'r').read().split()
        except:
            columns = 80
        columns = int(columns) - 10

        import textwrap
        for prefix in sorted(d):
            line = ", ".join(sorted(d[prefix]))
            indent = ' ' * (len(prefix) + 2)
            text = textwrap.fill(line, width=columns, initial_indent='',
                                 subsequent_indent=indent)
            print('{0}: {1}'.format(prefix, text))

