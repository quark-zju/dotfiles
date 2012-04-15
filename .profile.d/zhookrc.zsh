# do nothing if current shell is not zsh
[[ $SHELL =~ zsh$ ]] || return

# related helper functions {{{

# change title
title() {
    if [ $TERM != 'linux' ]; then
        print -Pn "\e]2;$@\a";
    fi
}

# cd back (or use zsh cdr)
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
# }}}

# zsh hook functions {{{
chpwd() {
    # modify title
    # if in ssh, add hostname
    if [[ -z "$SSH_CLIENT" ]]; then
        title "%1c"
    else
        title "%m: %1c"
    fi

    # push current path to $path_history (use zsh cdr instead)
    if [[ -z $cb_flag ]]; then
        path_history+=($PWD);
    fi
}

preexec() {
    # modify title to command name
    # if in ssh, add hostname
    # if $TITLE is non-empty, use it
    local ESCAPED_CONTENT;
    if [ -n "$TITLE" ]; then
        ESCAPED_CONTENT="$TITLE"
    else
        ESCAPED_CONTENT=`echo $1 | sed 's/[^a-zA-Z0-9_-. ].*$//g'`
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
# }}}

chpwd $PWD