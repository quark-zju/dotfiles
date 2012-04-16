# History, Cache {{{
local ZSH_CACHE=~/.cache/zsh
HISTFILE=$ZSH_CACHE/histfile
HISTSIZE=5000
SAVEHIST=5000
mkdir -p $ZSH_CACHE
# }}}

# Zstyles, Autoload, Completion {{{
zstyle ':completion:*' completer _complete _ignored _approximate
zstyle ':completion:*' group-name ''
zstyle ':completion:*' list-colors ''
zstyle ':completion:*' matcher-list 'm:{[:lower:]}={[:upper:]}' 'r:|[._-]=** r:|=**' 'l:|=* r:|=*'
zstyle ':completion:*' max-errors 2
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path $ZSH_CACHE/comp_cache
zstyle ':completion:*:functions' ignored-patterns '_*'
zstyle ':completion:*' menu select=8
zstyle ':completion:*' squeeze-slashes true
zstyle ':completion:*:*:kill:*:processes' list-colors '=(#b) #([0-9]#)*=0=01;31'
zstyle ':completion:*:*:kill:*:processes' command 'ps xo pid,user:10,cmd | grep -v "zsh$" | grep -v "\ssshd:"'
zstyle ':vcs_info:*' formats '%F{cyan}%s %B%b%f '
zstyle ':vcs_info:*' enable git svn
zstyle ':chpwd:*' recent-dirs-file $ZSH_CACHE/chpwd_recent

autoload -Uz compinit vcs_info zmv zcp zln add-zsh-hook zed zfinit select-word-style

# zftp
zfinit

# backward kill word now stops at /
select-word-style bash

# custom completion scripts
local CUSTOM_COMP_PATH=~/.profile.d/zcompletion
[[ -d $CUSTOM_COMP_PATH ]] && fpath=($CUSTOM_COMP_PATH $fpath)
compinit
# }}}

# Setopt, Bindkey {{{
setopt append_history inc_append_history autocd cshnullglob extendedglob short_loops hist_ignore_space hist_ignore_dups prompt_subst
bindkey -v
bindkey '^A' beginning-of-line
bindkey '^E' end-of-line
bindkey '^K' kill-line
bindkey '^L' clear-screen
bindkey '^R' history-incremental-search-backward
bindkey '^W' backward-kill-word
bindkey '^[.' insert-last-word
# auto replace ... to ../.. (from zsh-lovers)
rationalise-dot() {
    if [[ $LBUFFER = *.. ]] && [[ "$LBUFFER" = "$BUFFER" ]]; then
        LBUFFER+=/..
    else
        LBUFFER+=.
    fi
}
zle -N rationalise-dot
bindkey . rationalise-dot
# }}}

# Prompt {{{
# vcs_info_wrapper
_vcs_info() {
  vcs_info
  [[ -n "$vcs_info_msg_0_" ]] && echo -n "${vcs_info_msg_0_}"
}

if [[ -n "$SSH_TTY" ]]; then
	export PS1="%F{cyan}%U%n@%m%u%f %B%F{red}%(?..[%?] )%f%F{cyan}%#%f%b "
else
	export PS1="%F{g}%U%n%u%f %B%F{red}%(?..[%?] )%f%F{g}%#%f%b "
fi

export RPS1='$(_vcs_info)'"%B%F{yellow}%~%f%b"
# }}}

# No Beep {{{
setterm -blength 0
# }}}

# Title, Paths {{{
# change title
title() {
    [ $TERM != 'linux' ] && print -Pn "\e]2;$@\a"
}

chpwd() {
    # push current path to $path_history (use zsh cdr instead)
    [[ -z $cb_flag ]] && path_history+=($PWD)
}

preexec() {
    # modify title to command name
    # if in ssh, add hostname
    # if $TITLE is non-empty, use it
    emulate -L zsh
    local -a cmd
    cmd=(${(z)1})
    [[ -n "$TITLE" ]] && cmd[1]="$TITLE"
    if [[ -z "$SSH_CLIENT" ]]; then
        title $cmd[1]:t "$cmd[2,-1]"
    else
        title "%m: " $cmd[1]:t "$cmd[2,-1]"
    fi
}

precmd() {
    # modify title to partial path
    # if in ssh, add hostname
    if [[ -z "$SSH_CLIENT" ]]; then
        title "%2c"
    else
        title "%m: %2c"
    fi
}

cb() {
    # pop current pwd
    path_history[-1]=()
    # set flag
    cb_flag=1
    # top, -1 means the last element
    cd $path_history[-1]
    # unset flag
    unset cb_flag
}

precmd
# }}}

# Basic alias {{{
# short names
alias la='ls -A'
alias ll='ls -lh'
alias l='ls -CF'
alias md='mkdir -p'
alias rd='rmdir'
alias bd='bg && disown'
# default parameters
alias ls='ls --color=auto'
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
alias -g M='| most'
alias -g EM='|& most'
# }}}

# Load other stuff {{{
for i in /etc/profile.d/*.{sh,zsh} ~/.profile.d/*.{sh,zsh}; do
    if [ -e ${i:r}.zwc ]; then
        source ${i:r}.zwc
    else
        source $i
    fi
done
# }}}

# Deprecated {{{
# cdr (now use autojump)
if ! which autojump &>/dev/null; then
    autoload -Uz chpwd_recent_dirs cdr 
    add-zsh-hook chpwd chpwd_recent_dirs
fi

# }}}
