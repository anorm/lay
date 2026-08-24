# lay

`lay` is a command line tool for controlling the layout of panes in the current
tmux window using a short, declarative expression.

tmux ships with five preset layouts (`even-horizontal`, `even-vertical`,
`main-horizontal`, `main-vertical`, `tiled`). Anything else requires a sequence
of `split-window` and `resize-pane` calls, or hand-writing tmux's checksummed
layout strings. `lay` lets you describe the arrangement you want and applies it
in one atomic step.

```
lay '(4 4) / 1'
```

```
┌───────────┬───────────┐
│           │           │
│     0     │     1     │
│           │           │
├───────────┴───────────┤
│                       │
│           2           │
│                       │
└───────────────────────┘
```

## Installation

```sh
uv tool install git+https://github.com/anorm/lay
```

## Usage

```
lay [options] <layout>
```

The layout is a single argument, so it normally needs quoting:

```sh
lay '1 2'
```

Bare words that your shell will not mangle may be passed unquoted, and multiple
arguments are joined with spaces, so these are all equivalent:

```sh
lay '1 1 1'
lay 1 1 1
lay "1  1   1"
```

## The layout language

A layout expression is a tree. Every leaf is a pane. Every number is a
**weight** — weights are relative, not absolute, so `1 1` and `4 4` and
`50 50` all mean "two equal parts".

There are exactly two operators:

| Syntax  | Meaning                                        |
| ------- | ---------------------------------------------- |
| space   | side by side — **columns**, split left to right |
| `/`     | stacked — **rows**, split top to bottom         |
| `( … )` | grouping                                        |

`/` binds *tighter* than space, so `1 1 / 1` reads as `1 (1 / 1)`: a full-height
column on the left, a stacked pair on the right. Parenthesise to put the row
split on the outside: `(1 1) / 1`.

### Weights

A weight says how much of the available space that child takes, relative to its
siblings. Weights are shared out along the axis of the split — widths for
columns, heights for rows.

```sh
lay '1 2'        # two columns, the right one twice as wide
lay '1 / 3'      # two rows, the bottom one three times as tall
lay '2 3 5'      # three columns at 20% / 30% / 50%
```

Weights must be integers (not decimals). They must be positive.
Only the ratios matter, so `2 3 5` and `20 30 50` are the same layout.

### Grouping and nesting

Parentheses turn a sub-layout into a single child of its parent. Since `/` binds
tighter than a space, they are what makes a **row** the outer split:

```sh
lay '(1 1) / 2'
```

```
┌───────────┬───────────┐
│     0     │     1     │
├───────────┴───────────┤
│                       │
│           2           │
│                       │
└───────────────────────┘
```

Drop them and you get something quite different — a column of `1` beside a
stack of `1 / 2`:

```sh
lay '1 1 / 2'
```

```
┌───────────┬───────────┐
│           │     1     │
│           ├───────────┤
│     0     │           │
│           │     2     │
│           │           │
└───────────┴───────────┘
```

Nesting can go as deep as you like:

```sh
lay '1 / (1 (1 / 1 / 1)) / 1'
```

### Weighting a group

A bare group has a weight of **1**, the same as a bare `1` leaf. To give a group
a different weight, prefix it with `N:`:

```sh
lay '3:(1 1) 1'
```

```
┌─────────────┬─────────────┬───────┐
│      0      │      1      │   2   │
└─────────────┴─────────────┴───────┘
   ← ─────── 3 ─────── →     ← 1 → 
```

The same applies to an unparenthesised column, which is also implicitly
weight 1. These two are identical:

```sh
lay '1 / 1 2'
lay '1:(1 / 1) 2'
```

```
┌───────────┬───────────────────────┐
│     0     │                       │
├───────────┤           2           │
│     1     │                       │
└───────────┴───────────────────────┘
   width 1           width 2
```

To make the columns equal instead:

```sh
lay '2:(1 / 1) 2'
```

This rule keeps a group's weight independent of what is inside it — editing the
contents of a group never changes how much space the group itself gets.

### Grammar

```ebnf
layout  = cols ;
cols    = rows , { rows } ;          (* whitespace separated *)
rows    = item , { "/" , item } ;
item    = number
        | group
        | number , ":" , group ;
group   = "(" , layout , ")" ;
number  = ? decimal > 0 ?  ;
```

## Pane count and pane order

`lay` never creates or destroys panes by default. It first counts the leaves in
the expression and compares that to the number of panes in the target window.
If they differ, nothing is changed and `lay` exits with status 2:

```
$ lay '1 1 1'
lay: layout needs 3 panes, window has 2
```

Use `-c` / `--create` to let `lay` split off the missing panes first. Extra
panes are never killed — that always stays an explicit `kill-pane`.

`-n` / `--dry-run` skips this check entirely. A dry run only draws the shape
you asked for, so it neither counts nor touches the window's panes and can
never fail with status 2.

When the counts match, the *n*th leaf in the expression receives the *n*th pane
of the window. Leaves are numbered in the order they are written, depth first,
which means a group's contents are consumed before moving on to the group's
right/lower sibling:

```
lay '1 / 1 2'
     │   │ └── pane 2
     │   └──── pane 1
     └──────── pane 0
```

Panes therefore keep their tmux indices and only move on screen. If you want a
pane somewhere else, use `swap-pane`, or `lay -c` after `break-pane`.

## Editing the current layout

`lay -e` reads the window's existing arrangement, turns it back into a layout
expression, and opens it in `$EDITOR` (or `$VISUAL`, else `vi`). Save and exit
and the result is applied; quit without saving and nothing changes.

```sh
lay -e
```

```
(1 1) / 1

# Edit the layout, then save and exit. Lines starting with '#' are ignored,
# and emptying the file aborts without changing anything.
```

Nothing is stored on the window to make this work — the expression is
reconstructed from `#{window_layout}` every time. That means `-e` works on
windows `lay` has never touched, survives a tmux server restart, and can never
disagree with what is actually on screen.

The expression you get back is *canonical* rather than whatever was originally
typed. Weights are reduced to their simplest whole form and redundant
parentheses are dropped, so `(4 4) / 1` comes back as `(1 1) / 1` and
`(1 / 1) 2` as `1 / 1 2`. It describes exactly the same layout.

Panes are matched to leaves in the usual order, so editing only the weights
moves the boundaries and leaves every pane where it is. Adding or removing a
leaf changes the pane count, which is an ordinary mismatch — combine with `-c`
to have the missing panes split off for you:

```sh
lay -c -e
```

Layouts tmux built for itself (a mouse drag, or `select-layout tiled`) may have
no simple ratio behind them. Those still decode correctly, but the weights come
back as raw cell counts, so expect `89 88` rather than `1 1`.

## Options

| Option              | Description                                                     |
| ------------------- | --------------------------------------------------------------- |
| `-t <target>`       | Target window, in tmux `target-window` form. Defaults to current. |
| `-c`, `--create`    | Split to create missing panes instead of failing.                 |
| `-n`, `--dry-run`   | Print an ASCII diagram of the layout and exit without applying.   |
| `-e`, `--edit`      | Edit the window's current layout in `$EDITOR`.                    |
| `-v`, `--verbose`   | Report the parsed tree and the computed cell geometry.            |
| `-h`, `--help`      | Show usage.                                                       |
| `-V`, `--version`   | Show version.                                                     |

## Exit status

| Code | Meaning                                                      |
| ---- | ------------------------------------------------------------ |
| `0`  | Layout applied.                                              |
| `1`  | Usage error, the layout failed to parse, or the edit was abandoned. |
| `2`  | Pane count mismatch.                                         |
| `3`  | Layout does not fit — a pane would be smaller than 1 cell.   |
| `4`  | tmux is unavailable, the target window does not exist, or its layout could not be read. |

## Sizing details

Cells are integers, and every split consumes one column or row for the border
tmux draws between the two sides. For a window `W` columns wide holding `n`
columns of pane, `sum(widths) + (n - 1) == W`.

Weights are applied to the space left after subtracting borders, and the
remainder is distributed by largest fractional part, so the total always matches
the window exactly and the panes closest to their next whole cell are the ones
rounded up. A layout that would force any pane below one cell is rejected with
exit status 3 rather than being silently squashed.

## How it works

`lay` reads the window geometry from
`tmux display-message -p '#{window_width} #{window_height}'`, walks the parsed
tree assigning each node a rectangle, renders a native tmux layout string
(`843f,178x43,0,0{89x43,0,0,0,88x43,90,0,1}`) including the leading checksum,
and applies it with a single `tmux select-layout`. Because it is one call, there
is no intermediate flicker and no partially applied layout if something is
wrong.

Under `-n` the work stops after the geometry is computed: `lay` measures the
window, draws the diagram, and returns. That one `display-message` is the only
tmux command a dry run issues — it never lists panes, splits, or applies.

`-e` runs the same machinery backwards first. It reads `#{window_layout}`,
parses the tree tmux stores there, and recovers each split's weights by
searching for the simplest integers that reproduce the recorded cell sizes
exactly — which is how `89` and `88` columns become `1 1` again. The expression
that comes out is guaranteed to re-render to the layout it came from.

## Examples

```sh
lay '1 1 1'              # three equal columns
lay '1 2'                # two columns, 1:2
lay '(4 4) / 1'          # two equal columns above one full-width pane
lay '1 / 1 2'            # a stacked pair on the left, one wide pane right
lay '1 / 1 / 1'          # three equal rows
lay '(2 1) / 1'          # 2:1 columns on top, full-width row below
lay '3:(1 / 1 / 1) 1'    # tall three-row column at 75%, sidebar at 25%
lay -n '1 2 1'           # preview the layout without applying it
lay -e                   # edit the current layout in $EDITOR
lay -t dev:2 '1 1'       # target another window
```
