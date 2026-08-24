<#
.SYNOPSIS
    Declaration-only future entry point for safe local model installation.
.DESCRIPTION
    O01 will validate a manifest, reject a Git-worktree target, obtain only
    approved files, verify checksums, and report results. This skeleton makes no
    network request and writes no model file.
#>
param(
    [string]$Profile,
    [string]$ModelHome
)

throw 'O01: install_models has not been implemented.'
