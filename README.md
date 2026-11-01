dotfiles for configuration in my `$HOME`.

Usage
=====
Cherry-pick parts that are useful and symlink to this dotfiles repo.

Link selected entries into `$HOME` without overwriting existing paths:

```sh
./lns .config/sway .config/waybar .config/zsh .zshrc .gitconfig
```

Use additional config files for local customization, like:
- `.gitconfig.local`
- `.zshrc.local`

Related
=======
I also have a `etcfiles` repo for system configuration files.
