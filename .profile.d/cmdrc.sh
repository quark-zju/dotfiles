# mkdir and cd
mcd() {
	mkdir -p "$@"
	cd "$1"
}

# cd up
cu() {
	for i in `seq 1 ${1:-1}`; do cd ..; done
}

# mv $1 to dir $2, and link back
lmv() {
	[ -e "$1" -a -d "$2" ] && mv "$1" "$2"/ && ln -s "$2"/"$(basename "$1")" "$(dirname "$1")"; 
}

# empty file ?
empty() {
    [[ `stat -c%s "$1"` == 0 ]] 
}

# simple ping
ping1() {
	ping -W 1 -c 1 "$1" &>/dev/null && echo "$1"
}

# colorize output in red
# cat xxx | redize
redize() {
    while read line; do
        print '\e[91m'${(q)line}'\e[0m' > /dev/tty
        print -n $'\0'
    done
}

# simple compile and run or run screen (now tmux)
s() {
	if [ -e "$1" ]; then
		# detect compile flags
		cxxflags=()
		typeset -A cxxref
		cxxref=(mathlink.h '-pthread -lML32i3 -lrt' pthread '-pthread' boost/program_options '-lboost_program_options')
		file="$1"
		for key (${(k)cxxref}) {
			grep -q "#include.*$key" "$file" && cxxflags+=(${cxxref[$key]})
		}
		# use echo to reparse $cxxflags, do not regard it as a whole
		g++ "$file" -std=c++0x -Wall `echo $cxxflags` -lm && { stdbuf -o0 ./a.out && rm a.out &> /dev/null; }
	else
		\tmux attach || \tmux
	fi
}

# gvim, a directory or a file
g() {
    if [ -d "$1" ]; then
        pushd -q "$1"
        gvim -c 'NERDTree'
        popd -q
    else
        gvim "$@"
    fi
}

nocolorgcc() {
  # unset colorgcc path
  export PATH=`echo $PATH | sed 's#/usr/lib/colorgcc/bin:##'`
}


# run compiler with auto package parameters
vala() {
	if [[ "${#@}" < 3 ]]; then
		# smart detect packages needed
		pkgparams=()
		typeset -A packages
		packages=(Gst gstreamer-0.10 Gee gee-1.0 Gtk gtk+-2.0 Sqlite sqlite3)
		file="$1"
		for key (${(k)packages}) {
			grep -q "using $key;" "$file" && pkgparams+=(--pkg ${packages[$key]})
		}
		valac $pkgparams $@
	else
		valac $@
	fi
}

# tarxz, expect a directory name without tailing '/'
# tarxz directory/without/tailing/slash
tarxz() {
    if [ -n "$1" ]; then
        if which pv &>/dev/null; then
            tar cf - "$1" | pv | xz -9 > "$1.tar.xz"
        else
            tar cf - "$1" | xz -9 > "$1.tar.xz"
        fi
    fi
}

# GBK -> UTF8, only proccess non-utf8 files
# antigbk files
antigbk() {
    if [[ -z "$@" ]]; then
        cat | iconv -c -f GB18030 -t UTF8
    else
        for i in "$@"; do
            if file "$i" | fgrep ISO >/dev/null; then
                echo Converting "$i"...
                rm /tmp/_u &> /dev/null
                iconv -c -f GB18030 -t UTF8 < "$i" > /tmp/_u
                cp /tmp/_u "$i"
            fi
        done
    fi
}

# remove \r
# dox2unix files
dos2unix() {
    if [[ -z "$@" ]]; then
        cat | tr -d '\r'
    else
        for i in "$@"; do
            cat "$i" | tr -d '\r' > "$i.unix"
            rm "$i" && mv "$i.unix" "$i"
        done
    fi
}

# remove BOM
# rmbom files
antibom() {
    if [[ -z "$@" ]]; then
        cat | tr -d '\240\302\340\357\273\277'
    else
        for i in "$@"; do
            cat "$i" | tr -d '\240\302\340\357\273\277' > "$i.unix"
            rm "$i" && mv "$i.unix" "$i"
        done
    fi
}

# find pattern in files in currect dir
# grephs patten
greps() {
    # setopt cshnullglob extendedglob
    # no js here, it may be compressed
    grep --color=auto -HFn -A 3 -B 3 "$@" **{/*,}.{c,cc,cpp,h,hpp,rb,php,py,hs,txt,css,scss,sass,coffee,erb,slim,textile,rdoc,md,erb}
}

# resize a picture to lower resolution
# resize 1600 files
resize() {
    local s=800

    if echo "$1" | grep -q '^[1-9][0-9]*$'; then
        s=${1}
        shift
    fi

    for i in "$@"; do
        local size=`\identify "$i" | sed 's/+0+0.*//;s/.* //'`

        # adaptive-resize seems ignore filter setting, not using it here
        # convert -filter Hanning -adaptive-resize "${s}x${s}" "$i" "$i"

        printf "%s: %s -- " $i $size
        local width=`echo $size | sed 's/x.*//'`
        local height=`echo $size | sed 's/.*x//'`
        local rate

        # scale rate
        if [ $width -gt $height ]; then
            rate=$(printf 'scale=6;%s*100/%s\n' $s $width | \bc)
        else
            rate=$(printf 'scale=6;%s*100/%s\n' $s $height | \bc)
        fi

        # new width & height
        local nw=`printf '(%s*%s+50)/100\n' $width $rate | \bc`
        local nh=`printf '(%s*%s+50)/100\n' $height $rate | \bc`

        printf "%s%% --> %sx%s ... " $rate $nw $nh

        if [ $nw -lt $width ]; then
            # apply gamma fix (see http://www.4p8.com/eric.brasseur/gamma.html)
            convert "$i" -depth 16 -gamma 0.454545 -filter gaussian -resize "${nw}x${nh}" -gamma 2.2 -quality 95 -sampling-factor 1x1 "$i"
            printf "DONE\n"
        else
            printf "SKIPPED\n"
        fi
    done
}

# shuffle play music in current dir
shuffle_play() {
    pushd -q ${1:-$PWD}
    # use temp file, make 'q', ' ', '0' control keys available inside mplayer
local TITLE='shuffle_play'
ruby =(cat <<'EOF'
Dir['{,*/,*/*/,*/*/*/}*.{mp3,flac,ogg,wma}'].shuffle.each do |f|
puts f
exit unless system("mplayer -really-quiet '#{f.gsub "'", "'\"'\"'"}'")
end
EOF
)
    popd -q
}

# rails related, bundle exec wrapper
for i in rails rake thin unicorn puma warble; do
function $i {
    if [[ -e Gemfile ]] && cat Gemfile | grep -qF "$0"; then
        bundle exec $0 "$@"
    else
        command $0 "$@"
    fi
}
done

# pdf merge, output to merged.pdf
# mergepdfs files
mergepdfs() {
	gs -dNOPAUSE -sDEVICE=pdfwrite -sOUTPUTFILE=merged.pdf -dBATCH "$@"
}
# vim:ft=zsh
