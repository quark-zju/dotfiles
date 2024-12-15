
# Rust - rustup.
if [[ -d $HOME/.cargo/bin ]]; then
    PATH="$HOME/.cargo/bin:$PATH"
fi

# Ruby - rbenv.
hash rbenv &>/dev/null && eval "$(rbenv init -)"

# Nodejs - nvm.
if [[ -d "$HOME/.nvm" ]]; then
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
fi

# Locale.
export LC_ALL=en_US.UTF-8
