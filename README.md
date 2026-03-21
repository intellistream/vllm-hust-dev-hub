# vllm-hust-dev-hub

`vllm-hust-dev-hub` is a lightweight meta repository for daily development.

It provides a single VS Code multi-root workspace centered on `vllm-hust`, with room for related repositories that are commonly opened together during development, debugging, and upstream-sync work.

## Included Repositories

The default workspace includes these sibling repositories when they exist under `/home/shuhao`:

- `vllm-hust`
- `vllm-hust-workstation`
- `vllm-hust-website`
- `vllm-hust-docs`
- `reference-repos`

## Files

- `vllm-hust-dev-hub.code-workspace`: main multi-root workspace for VS Code.

## Usage

Open the workspace directly in VS Code:

```bash
code /home/shuhao/vllm-hust-dev-hub/vllm-hust-dev-hub.code-workspace
```

If you want to add more repositories, edit the workspace file and append another entry to `folders`.