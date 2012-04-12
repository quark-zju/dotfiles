" Vim color file
" Maintainer:   Jonathan Filip <jfilip1024@gmail.com>
" Last Modified: Wed Apr 01, 2009  10:03AM
" Version: 2.5
"
"
" GUI / 256 color terminal
"
" I started out trying to combine my favorite parts of other schemes and ended
" up with this (oceandeep, moria, peaksea, wombat, zenburn).
"
" This file also tries to have descriptive comments for each higlighting group
" so it is easy to understand what each part does.
"
" Modified by WU Jun <quark@zju.edu.cn>
" remove cterm settings
" add some additional highlights


set background=dark
hi clear
if exists("syntax_on")
    syntax reset
endif
let g:colors_name="mylucius"

" blue: 3eb8e5
" green: 92d400


" Base color
" ----------
hi Normal           guifg=#e4e4e4           guibg=#242424


" Comment Group
" -------------
" any comment
hi Comment          guifg=#808080                                   gui=NONE


" Constant Group
" --------------
" any constant
hi Constant         guifg=#50d6de                                   gui=NONE
" strings
hi String           guifg=#8ad6f2                                   gui=NONE
" character constant
hi Character        guifg=#8ad6f2                                   gui=NONE
" numbers decimal/hex
hi Number           guifg=#50d6de                                   gui=NONE
" true, false
hi Boolean          guifg=#50d6de                                   gui=NONE
" float
hi Float            guifg=#50d6de                                   gui=NONE


" Identifier Group
" ----------------
" any variable name
hi Identifier       guifg=#fcb666                                   gui=NONE
" function, method, class
hi Function         guifg=#fcb666                                   gui=NONE


" Statement Group
" ---------------
" any statement
hi Statement        guifg=#bae682                                   gui=NONE
" if, then, else
hi Conditional      guifg=#bae682                                   gui=NONE
" try, catch, throw, raise
hi Exception        guifg=#bae682                                   gui=NONE
" for, while, do
hi Repeat           guifg=#bae682                                   gui=NONE
" case, default
hi Label            guifg=#bae682                                   gui=NONE
" sizeof, +, *
hi Operator         guifg=#bae682                                   gui=NONE
" any other keyword
hi Keyword          guifg=#bae682                                   gui=NONE


" Preprocessor Group
" ------------------
" generic preprocessor
hi PreProc          guifg=#efefaf                                   gui=NONE
" #include
hi Include          guifg=#efefaf                                   gui=NONE
" #define
hi Define           guifg=#efefaf                                   gui=NONE
" same as define
hi Macro            guifg=#efefaf                                   gui=NONE
" #if, #else, #endif
hi PreCondit        guifg=#efefaf                                   gui=NONE


" Type Group
" ----------
" int, long, char
hi Type             guifg=#93e690                                   gui=NONE
" static, register, volative
hi StorageClass     guifg=#93e690                                   gui=NONE
" struct, union, enum
hi Structure        guifg=#93e690                                   gui=NONE
" typedef
hi Typedef          guifg=#93e690                                   gui=NONE


" Special Group
" -------------
" any special symbol
hi Special          guifg=#cfafcf                                   gui=NONE
" special character in a constant
hi SpecialChar      guifg=#cfafcf                                   gui=NONE
" things you can CTRL-]
hi Tag              guifg=#cfafcf                                   gui=NONE
" character that needs attention
hi Delimiter        guifg=#cfafcf                                   gui=NONE
" special things inside a comment
hi SpecialComment   guifg=#cfafcf                                   gui=NONE
" debugging statements
hi Debug            guifg=#cfafcf           guibg=NONE              gui=NONE


" Underlined Group
" ----------------
" text that stands out, html links
hi Underlined       guifg=fg                                        gui=underline


" Ignore Group
" ------------
" left blank, hidden
hi Ignore           guifg=bg


" Error Group
" -----------
" any erroneous construct
hi Error            guifg=#dd4040           guibg=NONE              gui=NONE


" Todo Group
" ----------
" todo, fixme, note, xxx
hi Todo             guifg=#deee33           guibg=NONE              gui=underline


" Spelling
" --------
" word not recognized
hi SpellBad         guisp=#ee0000                                   gui=undercurl
" word not capitalized
hi SpellCap         guisp=#eeee00                                   gui=undercurl
" rare word
hi SpellRare        guisp=#ffa500                                   gui=undercurl
" wrong spelling for selected region
hi SpellLocal       guisp=#ffa500                                   gui=undercurl


" Cursor
" ------
" character under the cursor
hi Cursor           guifg=bg                guibg=#8ac6f2
" like cursor, but used when in IME mode
hi CursorIM         guifg=bg                guibg=#96cdcd
" cursor column
hi CursorColumn                             guibg=#3d3d4d
" cursor line/row
hi CursorLine                               guibg=#3d3d4d


" Misc
" ----
" directory names and other special names in listings
hi Directory        guifg=#95e494                                   gui=NONE
" error messages on the command line
hi ErrorMsg         guifg=#ee0000           guibg=NONE              gui=NONE
" column separating vertically split windows
hi VertSplit        guifg=#777777           guibg=#444444           gui=NONE
" columns where signs are displayed (used in IDEs)
hi SignColumn       guifg=#9fafaf           guibg=#181818           gui=NONE
" line numbers
hi LineNr           guifg=#857b6f           guibg=#444444
" match parenthesis, brackets
hi MatchParen       guifg=#00ff00           guibg=NONE              gui=NONE
" text showing what mode you are in
hi MoreMsg          guifg=#2e8b57                                   gui=NONE
" the '~' and '@' and showbreak, '>' double wide char doesn't fit on line
hi ModeMsg          guifg=#90ee90           guibg=NONE              gui=NONE
" the 'more' prompt when output takes more than one line
hi NonText          guifg=#444444                                   gui=NONE
" the hit-enter prompt (show more output) and yes/no questions
hi Question         guifg=fg                                        gui=NONE
" meta and special keys used with map, unprintable characters
hi SpecialKey       guifg=#505050
" titles for output from :set all, :autocmd, etc
hi Title            guifg=#3eb8e5                                   gui=NONE
"hi Title            guifg=#5ec8e5                                   gui=NONE
" warning messages
hi WarningMsg       guifg=#e5786d                                   gui=NONE
" current match in the wildmenu completion
hi WildMenu         guifg=#000000           guibg=#cae682


" Diff
" ----
" added line
hi DiffAdd          guifg=fg                guibg=#008b8b
" changed line
hi DiffChange       guifg=fg                guibg=#008b00
" deleted line
hi DiffDelete       guifg=fg                guibg=#000000
" changed text within line
hi DiffText         guifg=fg


" Folds
" -----
" line used for closed folds
hi Folded           guifg=#a0a8b0           guibg=#404040           gui=NONE
" column on side used to indicated open and closed folds
hi FoldColumn       guifg=#b0d0e0           guibg=#305060           gui=NONE

" Search
" ------
" highlight incremental search text; also highlight text replaced with :s///c
hi IncSearch        guifg=#66ffff                                   gui=reverse
" hlsearch (last search pattern), also used for quickfix
hi Search                                    guibg=#ffaa33          gui=NONE

" Popup Menu
" ----------
" normal item in popup
hi Pmenu            guifg=#f6f3e8           guibg=#444444           gui=NONE
" selected item in popup
hi PmenuSel         guifg=#000000           guibg=#cae682           gui=NONE
" scrollbar in popup
hi PMenuSbar                                guibg=#607b8b           gui=NONE
" thumb of the scrollbar in the popup
hi PMenuThumb                               guibg=#aaaaaa           gui=NONE


" Status Line
" -----------
" status line for current window
hi StatusLine       guifg=#e0e0e0           guibg=#444444           gui=NONE
" status line for non-current windows
hi StatusLineNC     guifg=#777777           guibg=#444444           gui=NONE


" Tab Lines
" ---------
" tab pages line, not active tab page label
hi TabLine          guifg=#b6bf98           guibg=#181818           gui=NONE
" tab pages line, where there are no labels
hi TabLineFill      guifg=#cfcfaf           guibg=#181818           gui=NONE
" tab pages line, active tab page label
hi TabLineSel       guifg=#efefef           guibg=#1c1c1b           gui=NONE

" Visual
" ------
" visual mode selection
hi Visual           guifg=NONE              guibg=#445566
" visual mode selection when vim is 'not owning the selection' (x11 only)
hi VisualNOS        guifg=fg                                        gui=underline

" Override default settings
" -------------------------
" current line numbers
hi CursorLineNr guifg=#ffaa33  guibg=#444444
hi LineNr       guibg=#2e2e2e
" right column margin
hi ColorColumn  guibg=#222222
" cursor column/line
hi CursorColumn guibg=#333333
hi CursorLine   guibg=#333333
hi MatchParen   guifg=bg  guibg=#fa3 gui=bold
" bold
hi Statement    gui=bold
" showmarks (seems gui=none will be ignored, use all gui=bold here)
hi ShowMarksHLl guibg=#bae682 guifg=bg gui=bold
hi ShowMarksHLu guibg=#50d6de guifg=bg gui=bold
hi ShowMarksHLo guifg=#ddd guibg=#2e2e2e gui=bold
hi ShowMarksHLm guifg=#ddd guibg=#2e2e2e gui=bold

