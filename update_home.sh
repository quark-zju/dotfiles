#!/bin/zsh

autoload colors
colors

cd $(dirname `readlink -f "$0"`)
SELF_BASENAME=`basename $0`

for i in `find`; do
    [[ $i =~ '\.git$' ]] && continue
    [[ $i =~ '\.gitignore' ]] && continue
    [[ $i =~ '\.gitmodules' ]] && continue
    [[ $i =~ '\.git/' ]] && continue
    [[ $i =~ '^\./README' ]] && continue
    [[ -f $i ]] || continue

    FILE_BASENAME=`basename $i`
    [[ $FILE_BASENAME == $SELF_BASENAME ]] && continue

    # create if not existed
    if ! [[ -f $HOME/$i ]]; then
        # need create
        printf "\n$fg[white]$i: $fg[blue]Creating... "
        SRC_MOD=`stat -c %a $i`

        # check directory and create
        DEST_DIR=`dirname $HOME/$i`
        if [[ ! -d $DEST_DIR ]]; then
            printf '(new dir) '
            mkdir -p $DEST_DIR
        fi

        if [[ -d $DEST_DIR ]]; then
            install -m $SRC_MOD -p -T $i $HOME/$i
            print "Done"
        else
            print "$fg[red]Failed"
        fi

        if cat "$HOME/$i" | grep -qF '[TODO]'; then
            print "\n$fg[white]$i: $fg[yellow]Please fill [TODO] manually."
        fi

        continue
    fi

    # check [TODO] templates 
    if cat $i | grep -qF '[TODO]'; then
        if diff -Eb  --suppress-common-lines  $i "$HOME/$i" | grep '^<' | grep -vq TODO; then
            print "\n$fg[white]$i: $fg[yellow]Please check manually."
        elif cat "$HOME/$i" | grep -qF '[TODO]'; then
            print "\n$fg[white]$i: $fg[yellow]Please fill [TODO] manually."
        else
            printf "$fg[green]."
        fi
        continue
    fi

    # check file ident
    if diff -q "$HOME/$i" $i &>/dev/null; then
        # same file
        printf "$fg[green]."
        continue
    fi

    # check file datetime
    if [[ "$HOME/$i" -nt $i ]]; then
        # home has newer file
        print "\n$fg[white]$i: $fg[red]User has newer version$fg[yellow]"
        diff "$i" "$HOME/$i" 
    else
        # home has older or different file
        # need update
        printf "\n$fg[white]$i: $fg[blue]Updating... "
        DEST_MOD=`stat -c %a $HOME/$i`
        DEST_GROUP=`stat -c %g $HOME/$i`
        DEST_USER=`stat -c %u $HOME/$i`

        # install
        install -g $DEST_GROUP -o $DEST_USER -m $DEST_MOD -p -T $i $HOME/$i
        print "Done"
    fi
done

print ''

