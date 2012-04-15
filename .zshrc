# History, Cache {{{
HISTFILE=$ZSH_CACHE/histfile
HISTSIZE=5000
SAVEHIST=5000
local ZSH_CACHE=~/.cache/zsh
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
zstyle ':completion:*:*:kill:*' menu yes select
zstyle ':completion:*:kill:*' force-list always
zstyle ':completion:*:*:cdr:*:*' menu selection
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
bindkey -e
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

# Deprecated {{{

# colorize stderr in red
# exec 2>>(while read line; do
#   print '\e[91m'${(q)line}'\e[0m' > /dev/tty; print -n $'\0'; done &)

# }}}
