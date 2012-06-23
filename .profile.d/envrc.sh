# locale
if locale -a | grep -Fq 'zh_CN.utf8'; then
    export LANG=en_US.UTF-8
    export LC_CTYPE="zh_CN.UTF-8" # KDE needs this
    export LC_NUMERIC="en_US.UTF-8"
    export LC_TIME="en_US.UTF-8"
    export LC_COLLATE="en_US.UTF-8"
    export LC_MONETARY="en_US.UTF-8"
    export LC_MESSAGES="en_US.UTF-8"
    export LC_PAPER="en_US.UTF-8"
    export LC_NAME="en_US.UTF-8"
    export LC_ADDRESS="en_US.UTF-8"
    export LC_TELEPHONE="en_US.UTF-8"
    export LC_MEASUREMENT="en_US.UTF-8"
    export LC_IDENTIFICATION="en_US.UTF-8"
    export LESSCHARSET=utf-8
fi

# prepend PATHs
local PATH_PREPEND=''
for p in /usr/lib/colorgcc/bin $HOME/batch .; do
    if (! echo $PATH:$PATH_PREPEND | fgrep -q ":$p") && [ -e "$p" ]; then
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
