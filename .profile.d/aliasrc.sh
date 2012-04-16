# short names
exists() {
    which "$@" &>/dev/null
}
alias ip6='ip -f inet6'
exists bundle && alias be='bundle exec'
exists sdlmame && alias mame=sdlmame
exists proxychains && alias pc='proxychains'
exists tmux && alias t=tmux
exists lrun && alias m='DEBUG=1 lrun --reset-env false --network true --isolate-process false'
if exists rails; then
    alias p='RAILS_ENV=production'
    alias e='RAILS_ENV=staging'
    alias d='RAILS_ENV=development'
fi


# default parameters
alias audacious='audacious2 -i gtkui'
alias bc='bc -l'
alias df='df -h'
alias dosfsck='dosfsck -r -w -v'
alias du='du -hs'
alias fc='fc -e vim'
alias fgrep='fgrep --colour=auto'
alias grep='grep --colour=auto'
alias gvim='gvim -p'
alias locate='locate -b'
alias math='rlwrap math'
alias mysqldump='mysqldump --max_allowed_packet=90M'
alias rara='rar a -s -m4 -ol'
alias rdesktop='rdesktop -5 -z -r sound:local -r disk:Temp=/tmp -K -g 1280x782 -p -'
alias freerdp='xfreerdp -a 16 -g 1280x782 -z -x 95' 
alias screen='screen -R'
alias ssh='ssh -Y'
alias sshfs='sshfs -o follow_symlinks'
alias luit='luit -x -encoding gbk'
alias valgrind='valgrind --tool=memcheck --leak-check=yes'
alias wget='wget -c --timeout=5'
alias wine='env LANG=zh_CN.UTF-8 wine '
alias zip='zip -r'

# sudo
alias umount='sudo umount'
alias mount='sudo mount'

# alias -s, -g requires zsh
[[ $SHELL =~ zsh$ ]] || return

local PLAYER=mplayer

# file extensions
alias -s bz2=tar xvf
alias -s chm=gnochm
alias -s c=tcc -run
alias -s gz=tar xvf
alias -s jar=java -jar
alias -s lua=lua
alias -s mo=msgunfmt
alias -s nes=fceux 
alias -s nsf=nosefart
alias -s pdf=evince
alias -s rar=unrar x
alias -s rb=ruby -Ku

alias -s doc=winword
alias -s docx=winword
alias -s pps=powerpnt
alias -s ppt=powerpnt
alias -s pptx=powerpnt

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

autoload -U pick-web-browser
alias -s com=pick-web-browser
alias -s net=pick-web-browser
alias -s org=pick-web-browser

