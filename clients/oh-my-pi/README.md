# Oh My Pi
> A coding agent with the IDE wired in. https://omp.sh

* https://github.com/can1357/oh-my-pi

## Dockerfile Patch
* This adds an extra stage (final stage) that runs as user privileges (me)
* Bakes in config for llama-swap (`./agent/*`) and themes etc so OMP is ready to rock

Apply the patch like this:

```bash
git am Dockerfile.patch    # applies as a proper commit
# NOT
git apply Dockerfile.patch # works too, but skips the commit metadata
```

## Alias
* Mounts CWD in at /work, with SELinux
* Uses keep-id so UID/GIDs are remapped and mount is R/W by user

```bash
alias omp='docker run --rm -it --userns keep-id -v "$(pwd):/work:Z" berne/oh-my-pi'
```
