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
zstyle ':completion:*:*:kill:*:processes' list-colors '=(#b) #([0-9]#)*=0=01;31'
zstyle ':completion:*:*:kill:*:processes' command 'ps xo pid,user:10,cmd | grep -v "zsh$" | grep -v "\ssshd:"'
zstyle ':vcs_info:*' formats '%F{cyan}%s %B%b%f '
zstyle ':vcs_info:*' enable git svn
zstyle ':chpwd:*' recent-dirs-file $ZSH_CACHE/chpwd_recent

autoload -Uz compinit vcs_info zmv zcp zln chpwd_recent_dirs cdr add-zsh-hook zed
add-zsh-hook chpwd chpwd_recent_dirs

# custom completion scripts
local CUSTOM_COMP_PATH=~/.profile.d/zcompletion
[[ -d $CUSTOM_COMP_PATH ]] && fpath=($CUSTOM_COMP_PATH $fpath)
compinit
# }}}

# Setopt, Bindkey {{{
setopt append_history autocd cshnullglob extendedglob short_loops hist_ignore_space hist_ignore_dups prompt_subst
bindkey -v
bindkey '^A' beginning-of-line
bindkey '^E' end-of-line
bindkey '^K' kill-line
bindkey '^L' clear-screen
bindkey '^R' history-incremental-search-backward
bindkey '^W' backward-kill-word
bindkey '^[.' insert-last-word
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

# Term Settings, Beep {{{
setterm -blength 0
# }}}

# Load other stuff {{{
for i in /etc/profile.d/*.{sh,zsh} ~/.profile.d/*.{sh,zsh}; do
    source $i
done
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
    local ESCAPED_CONTENT;
    if [ -n "$TITLE" ]; then
        ESCAPED_CONTENT="$TITLE"
    else
        ESCAPED_CONTENT=`echo $1 | cut -d ' ' -f 1,2,3`
    fi
    if [[ -z "$SSH_CLIENT" ]]; then
        title "$ESCAPED_CONTENT"
    else
        title "%m: $ESCAPED_CONTENT"
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

