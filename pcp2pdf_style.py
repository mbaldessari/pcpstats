# pcp_style - pcp(1) report graphing utility
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

from reportlab.lib.styles import ParagraphStyle as PS
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus.frames import Frame
from reportlab.lib.units import inch
import reportlab.lib.colors

tablestyle = [ ('GRID', (0,0), (-1,-1), 1, reportlab.lib.colors.black),
               ('ALIGN', (0,0), (-1,-1), 'LEFT'),
               ('LEFTPADDING', (0,0), (-1,-1), 3),
               ('RIGHTPADDING', (0,0), (-1,-1), 3),
               ('FONTSIZE', (0,0), (-1,-1), 10),
               ('FONTNAME', (0,0), (-1,0), 'Times-Bold'), ]

class PcpDocTemplate(BaseDocTemplate):
    """Custom Doc Template in order to have bookmarks
    for certain type of text"""
    def __init__(self, filename, **kw):
        self.allowSplitting = 0
        apply(BaseDocTemplate.__init__, (self, filename), kw)
        template = PageTemplate('normal', [Frame(0.1*inch, 0.1*inch,
                                11*inch, 8*inch, id='F1')])
        self.addPageTemplates(template)

        self.centered = PS(
            name='centered',
            fontSize=30,
            leading=16,
            alignment=1,
            spaceAfter=20)

        self.centered_index = PS(
            name='centered_index',
            fontSize=24,
            leading=16,
            alignment=1,
            spaceAfter=20)

        self.small_centered = PS(
            name='small_centered',
            fontSize=14,
            leading=16,
            alignment=1,
            spaceAfter=20)

        self.h1 = PS(
            name='Heading1',
            fontSize=16,
            leading=16)

        self.h2 = PS(
            name='Heading2',
            fontSize=14,
            leading=14)

        self.h2_center = PS(
            name='Heading2Center',
            alignment=1,
            fontSize=14,
            leading=14)

        self.h2_invisible = PS(
            name='Heading2Invisible',
            alignment=1,
            textColor='#FFFFFF',
            fontSize=14,
            leading=14)

        self.mono = PS(
            name='Mono',
            fontName='Courier',
            fontSize=16,
            leading=16)

        self.normal = PS(
            name='Normal',
            fontSize=16,
            leading=16)

        self.toc = TableOfContents()
        self.toc.levelStyles = [
            PS(fontName='Times-Bold', fontSize=14, name='TOCHeading1',
                leftIndent=20, firstLineIndent=-20, spaceBefore=2, leading=16),
            PS(fontSize=10, name='TOCHeading2', leftIndent=40,
                firstLineIndent=-20, spaceBefore=0, leading=8),
        ]

    def afterFlowable(self, flowable):
        """Registers TOC entries."""
        if flowable.__class__.__name__ == 'Paragraph':
            text = flowable.getPlainText()
            style = flowable.style.name
            if style in ['Heading1', 'centered_index']:
                level = 0
            elif style in ['Heading2', 'Heading2Center', 'Heading2Invisible']:
                level = 1
            else:
                return
            entry = [level, text, self.page]
            #if we have a bookmark name append that to our notify data
            bookmark_name = getattr(flowable, '_bookmarkName', None)
            if bookmark_name is not None:
                entry.append(bookmark_name)
            self.notify('TOCEntry', tuple(entry))
            self.canv.addOutlineEntry(text, bookmark_name, level, True)
