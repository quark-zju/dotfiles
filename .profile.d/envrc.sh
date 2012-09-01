# locale
if [ -n "$LANG" ] && locale -a | grep -Fq 'zh_CN.utf8'; then
    export LANG=en_US.UTF-8
    export LC_CTYPE=zh_CN.UTF-8 # KDE needs this
fi

# prepend PATHs
local PATH_PREPEND=''
for p in /usr/lib/colorgcc/bin $HOME/batch $HOME/bin/scripts $HOME/bin $HOME/.rbenv/bin .; do
    if (! echo $PATH:$PATH_PREPEND | fgrep -q "$p:") && [ -d "$p" ]; then
        PATH_PREPEND=${PATH_PREPEND}${p}:
    fi
done
export PATH=${PATH_PREPEND}${PATH}

# wine: no shortcuts, no verbose output
export WINEDLLOVERRIDES="winemenubuilder.exe=d"
export WINEDEBUG=err-all,fixme-all,warn-all

# utils
export EDITOR='gvim -f'

# java workarounds
export AWT_TOOLKIT="MToolkit"
# export _JAVA_OPTIONS="-Dawt.useSystemAAFontSettings=lcd -Dswing.aatext=true"

# dynamically set pulse server according to ssh_client
if [ -n "$SSH_CLIENT" ]; then
    export PULSE_SERVER=${SSH_CLIENT/ [ 0-9]*/}
fi
