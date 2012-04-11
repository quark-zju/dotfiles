Here is some of my ([quark\_zju](https://twitter.com/Quark_zju)'s) dotfiles.

About
=====
I use zsh, gvim, ruby, i3, git ....

You may find these dotfiles useful if you use these tools as well.

Any comments are welcome :p

Usage
=====
Just run `update_home.sh` in terminal (zsh required).
This script will update non-existed, out-dated dotfiles in home. 
If conflicts are found, nothing will be written but file names are printed.

Notes
=====
fonts
-----
* Install DroidSans to display CJK and Thai characters correctly.
* Install Terminus as terminal / gvim font. If you do not like bitmap fonts,
  Dejavu Sans Mono and Droid Sans Mono are good terminal fonts.

gemrc
-----
* Currently `ruby.taobao.org` is in `.gemrc`, you may want to
  change it to `rubygems.org`.

vim
---
* I use [Vundle](https://github.com/gmarik/vundle) to manage vim packages. For Vundle to work properly, `git clone https://github.com/gmarik/vundle.git ~/.vim/bundle/vundle`.
* To install vim packages, start vim and use `:BundleInstall` command.
* You may want to run `cd ~/.vim/ && ln -s bundle/ultisnips/UltiSnips snippets_basic` to
  workaround ultisnip's 'duplicated' snippets issue.
