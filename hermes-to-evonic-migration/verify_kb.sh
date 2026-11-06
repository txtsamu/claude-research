#!/bin/sh
# Run as root on home. Read-only checks of each imported agent KB (as the evonic user).
E="runuser -u evonic -- /run/current-system/sw/bin/evomem"
printf '%-18s %-5s %s\n' agent md_files "index (docs / chunks / links / dangling)"
for id in default audio critic dev device diskos finance net ops research uiux; do
  kb=/var/lib/evonic/agents/hermes_$id/kb
  files=$(find $kb -name '*.md' | wc -l)
  st=$($E --knowledge $kb stats 2>&1 | python3 -c '
import re,sys
t=sys.stdin.read()
m=re.search(r"docs: (\d+) live.*?chunks: (\d+).*?links: (\d+) \((\d+) dangling\)",t,re.S)
print(" / ".join(m.groups()) if m else "NO INDEX: "+t[:60].replace("\n"," "))')
  printf '%-18s %-5s %s\n' "hermes_$id" "$files" "$st"
done
echo; echo "== validate ALL files in the biggest KBs (--since 0 = no recency window):"
for id in default ops; do
  printf '%-14s ' "hermes_$id"; $E --knowledge /var/lib/evonic/agents/hermes_$id/kb validate --since 0 2>&1 | tail -1 | cut -c1-100
done
echo; echo "== search in hermes_ops KB:"
$E --knowledge /var/lib/evonic/agents/hermes_ops/kb search "armbian tv box reboot hang" 2>&1 | head -6 | cut -c1-150
echo; echo "== search in hermes_default KB:"
$E --knowledge /var/lib/evonic/agents/hermes_default/kb search "truenas nfs mount" 2>&1 | head -5 | cut -c1-150
