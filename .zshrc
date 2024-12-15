# Alias {{{
# short names
alias md='mkdir -p'
alias rd='rmdir'
alias bd='bg && disown'
alias ip6='ip -f inet6'
alias d='git diff --no-index'

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

# file extensions
alias -s c=tcc -run
alias -s jar=java -jar
alias -s lua=lua
alias -s nes=fceux
alias -s nsf=nosefart
alias -s pdf=evince
alias -s rb=ruby -Ku

local PLAYER=${PLAYER:-xdg-open}
alias -s ape=$PLAYER
alias -s avi=$PLAYER
alias -s flac=$PLAYER
alias -s flv=$PLAYER
alias -s mkv=$PLAYER
alias -s mp3=$PLAYER
alias -s mpg=$PLAYER
alias -s ogg=$PLAYER
alias -s rm=$PLAYER
alias -s rmvb=$PLAYER
alias -s wma=$PLAYER
alias -s wmv=$PLAYER

function browse() {
    local url="$1"
    if [[ $url == *://* ]]; then
        xdg-open "$url"
    else
        xdg-open "https://$url"
    fi
}

alias -s cn=browse
alias -s com=browse
alias -s net=browse
alias -s org=browse
alias -s io=browse
alias -s fm=browse
# }}}

# ZLE {{{
autoload -Uz select-word-style edit-command-line

# Ctrl+W stops at /
select-word-style bash

# ESC, e edits the lommanj line (by grml zshrc)
# }}}

# Environments {{{
# PATH - Include ~/bin.
PATH="$HOME/bin:$HOME/.cargo/bin:$PATH"

# Editor - Prefer gvim, nvim.
if hash gvim 2>/dev/null; then
    EDITOR='gvim -f'
elif hash nvim 2>/dev/null; then
    EDITOR='nvim'
fi

# Dynamically set pulse server according to ssh_client
if [[ -n $SSH_CLIENT ]]; then
    export PULSE_SERVER="${SSH_CLIENT/ [ 0-9]*/}"
fi
# }}}

# Load other configs {{{
# Main zshrc
source ~/.config/zsh/grml-zshrc

# Autojump
PATH="$PATH:$HOME/.config/zsh/autojump/bin"
source ~/.config/zsh/autojump/bin/autojump.zsh

# Plugins
for i in ~/.config/zsh/*/*.plugin.zsh; do
    source "$i"
done

# https://bugs.launchpad.net/ubuntu-gnome/+bug/1193993
[ -f /etc/profile.d/vte.sh ] && source /etc/profile.d/vte.sh

# cargo target
if grep -q /tmp/cargo-target ~/.cargo/config 2>/dev/null; then
  mkdir -p /tmp/cargo-target
fi

# }}}

# bun {{{
if [[ -d "$HOME/.bun" ]]; then
  export BUN_INSTALL="$HOME/.bun"
  [[ -d "$BUN_INSTALL/_bun" ]] && source "$BUN_INSTALL/_bun"
  export PATH="$BUN_INSTALL/bin:$PATH"
fi
# }}}
