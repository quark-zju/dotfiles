
# Rust - rustup.
if [[ -d $HOME/.cargo/bin ]]; then
    PATH="$HOME/.cargo/bin:$PATH"
fi

# Ruby - rbenv.
hash rbenv &>/dev/null && eval "$(rbenv init -)"

# Locale.
export LC_ALL=en_US.UTF-8
