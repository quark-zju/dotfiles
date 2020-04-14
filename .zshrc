# Alias {{{
# short names
alias md='mkdir -p'
alias rd='rmdir'
alias bd='bg && disown'
# default parameters
alias rm='rm -v'
alias mv='mv -vi'
alias cp='cp -aviu'
alias scp='noglob scp -r'
# suffix
alias -g L='| less'
alias -g N='&> /dev/null'
alias -g S='&> /dev/null &!'
alias -g CE='2> >(while read line; do print "\e[91m"${(q)line}"\e[0m"; done)'
alias -g EL='|& less'
alias -g H='| head'
alias -g EH='|& head'
alias -g T='| tail'
alias -g ET='|& tail'
# }}}

# Load Plugins {{{
source ~/.config/zsh/grml-zshrc

PATH=$PATH:~/.config/zsh/autojump/bin
source ~/.config/zsh/autojump/bin/autojump.zsh

for i in ~/.config/zsh/*/*.plugin.zsh; do
    source "$i"
done
# }}}
