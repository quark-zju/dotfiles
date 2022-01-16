Here is some of my ([quark\_zju](https://twitter.com/Quark_zju)'s) dotfiles.

About
=====
I use zsh, gvim, ruby, i3, git ....

You may find these dotfiles useful if you use these tools as well.

Any comments are welcome :p

Usage
=====
Feel free to copy and edit these files.

`update_home.sh` updates non-existed or out-dated dotfiles in home. 
If conflicts (home version is newer and different) are found,
nothing will be written but filenames are printed.

Notes
=====
vim
---
* I use [Vundle](https://github.com/gmarik/vundle) to manage vim packages.
  For Vundle to work properly, `git clone https://github.com/gmarik/vundle.git ~/.vim/bundle/Vundle.vim`
* To install vim packages, start vim then `:BundleInstall`
* To enable UltiSnips builtin snippets: 
  `cd ~/.vim/ && ln -s bundle/ultisnips/UltiSnips snippets_basic` 

fonts
-----
* Default UI font is Droid Sans. It contains CJK and Thai characters.
* Default monospace font is JetBrains Mono.

rubygem
-------
* `ruby.taobao.org` is currently the only source. You may want to edit
  `.gemrc`.

