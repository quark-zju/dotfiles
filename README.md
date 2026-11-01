dotfiles for configuration in my `$HOME`.

Usage
=====
Cherry-pick parts that are useful and symlink to this dotfiles repo.

Link selected entries into `$HOME` without overwriting existing paths:

```sh
./lns .config/sway .config/waybar .zshrc
```

`lns` creates relative symlinks and reports a result for each argument. Bare
relative paths prefer the repo root; `./` and `../` use the current directory.
Paths under HOME or the repo may also be absolute. Correct existing links are
left alone; other existing destinations are reported as `conflict`. Conflicts
or errors produce exit status 1 after processing all arguments. See `./lns --help`.

Use additional config files for local customization, like:
- `.gitconfig.local`
- `.zshrc.local`

Related
=======
I also have a `etcfiles` repo for system configuration files.
