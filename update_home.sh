#!/bin/zsh

autoload colors
colors

SELF_BASENAME=`basename $0`

for i in `find`; do
  [[ $i =~ .git ]] && continue
  [[ $i =~ README ]] && continue

  FILE_BASENAME=`basename $i`
  if [[ -f $i ]] && [[ $FILE_BASENAME != $SELF_BASENAME ]]; then
    if [[ "$HOME/$i" -nt $i ]]; then
      # system has newer file
      print "\n$fg[white]$i: $fg[red]User has newer version$fg[yellow]"
      diff "$i" "$HOME/$i" 
    else
      # system has older or different file
      if [[ -f $HOME/$i ]]; then
        if diff -q "$HOME/$i" $i &>/dev/null; then
          # same file
          printf "$fg[green]."
        else
          # need update
          printf "\n$fg[white]$i: $fg[blue]Updating... "
          DEST_MOD=`stat -c %a $HOME/$i`
          DEST_GROUP=`stat -c %g $HOME/$i`
          DEST_USER=`stat -c %u $HOME/$i`

          # install
          install -g $DEST_GROUP -o $DEST_USER -m $DEST_MOD -p -T $i $HOME/$i
          print "Done"
        fi
      else
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
      fi
    fi
  fi
done

print ''

