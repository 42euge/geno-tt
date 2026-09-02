# TT

TT organizes code work and its live user-interface surfaces across local and
remote hosts. Its shared language connects canonical workspaces, dot-notation
concerns, and the windows or tabs used to work on them.

## Language

**Workspace**:
A canonical directory containing one or more repositories for a bounded piece
of work.

**Area**:
The first segment of a dot-notation node, grouping related concerns such as
`geno` in `geno.geno-tt`.
_Avoid_: Screen area, zone

**Node**:
A dot-notation identity for one logical concern, to which live surfaces attach.
_Avoid_: Window group, category

**Surface**:
A live user-interface instance attached to a node, such as a VS Code window,
iTerm tab, or browser group.
_Avoid_: App, workspace

**Zone**:
A named physical region in a window layout, independent of a logical area.
_Avoid_: Area, category

**Layout Profile**:
A named set of rules mapping categorized surfaces to zones.
_Avoid_: Window category, Rectangle profile
