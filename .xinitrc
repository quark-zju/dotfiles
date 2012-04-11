#!/bin/bash

# load user Xdefaults and keymaps
userresources=$HOME/.Xdefaults
usermodmap=$HOME/.xmodmaprc
sysresources=/etc/X11/xinit/.Xresources
sysmodmap=/etc/X11/xinit/.Xmodmap
[ -f $sysresources ] && xrdb -merge $sysresources
[ -f $sysmodmap ] && xmodmap $sysmodmap
[ -f $userresources ] && xrdb -merge $userresources
[ -f $usermodmap ] && xmodmap $usermodmap

# X Custom settings
xset r rate 400 60
xset b off
xbacklight -set 70

# alternative gtkrc-2.0 location
# export GTK2_RC_FILES=$HOME/.gtkrc-2.0

# ibus
export GTK_IM_MODULE=ibus
export XMODIFIERS=@im=ibus
export QT_IM_MODULE=ibus
ibus-daemon -rxd

# nm-applet
if pidof NetworkManager &>/dev/null && which nm-applet &>/dev/null; then
    nm-applet &
fi

# timidity++ Server (for PulseAudio, timidity can not run in system-wide daemon mode)
# exec timidity -iA -OO
# exec fluidsynth -i -s -a pulseaudio -m alsa_seq -r 44100 -g 1 -o synth.audio-channels=32 -o synth.audio-groups=32 -o synth.cpu-cores=2 /usr/share/soundfonts/SGM-V2.01.sf2

# synergy
# synergyc synergy-server
# exec synergys -c /etc/synergy.conf

# i3
exec ck-launch-session i3

