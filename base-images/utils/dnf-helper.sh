#!/usr/bin/env bash
set -Eeuxo pipefail

# Konflux buildah overlays cachi2/hermeto RPM repos at /etc/yum.repos.d when it
# finds repos.d/cachi2.repo. In-cluster ("localhost") builds have skipped that
# overlay, so hermetic dnf then hits the base image's mirrors.centos.org metalink
# and fails with "Could not resolve host". Copy prefetched repos when missing.
enable_cachi2_rpm_repos() {
    local reposdir="/cachi2/output/deps/rpm/$(uname -m)/repos.d"
    if [[ -f /etc/yum.repos.d/cachi2.repo || -f /etc/yum.repos.d/hermeto.repo ]]; then
        return 0
    fi
    if [[ ! -d "${reposdir}" ]]; then
        return 0
    fi
    shopt -s nullglob
    local repos=("${reposdir}"/*.repo)
    if ((${#repos[@]} == 0)); then
        return 0
    fi
    echo "Prefetched RPM repos not mounted at /etc/yum.repos.d; copying from ${reposdir}"
    rm -f /etc/yum.repos.d/*.repo
    cp -a "${repos[@]}" /etc/yum.repos.d/
}

enable_cachi2_rpm_repos

# Verified against dnf 4.14.0 on UBI9/RHEL 9.7 (dnf config-manager --dump)
DNF_OPTS=(
    -y
    --nodocs
    # do not set --noplugins, we do need subscription-manager plugin
    --setopt=install_weak_deps=0
    --setopt=max_parallel_downloads=10
    --setopt=keepcache=0
    --setopt=deltarpm=0
)

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    upgrade)
        # Problem: The operation would result in removing the following protected packages: systemd
        #  (try to add '--allowerasing' to command line to replace conflicting packages or '--skip-broken' to skip uninstallable packages)
        # Solution: --best --skip-broken does not work either, so use --nobest
        dnf upgrade --refresh --nobest --skip-broken "${DNF_OPTS[@]}" "$@"
        ;;
    install)
        dnf install "${DNF_OPTS[@]}" "$@"
        ;;
    *)
        echo "Usage: $0 {upgrade|install} [packages...]"
        exit 1
        ;;
esac

dnf clean all
rm -rf /var/cache/yum /var/cache/dnf
