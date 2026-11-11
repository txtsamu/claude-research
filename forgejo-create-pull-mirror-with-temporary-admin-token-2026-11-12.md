---
type: how-to
tags: [forgejo, k3s, homelab, pull-mirror, github, api, access-token, diskos]
created: 2026-11-12
last_verified: 2026-11-12
status: current
---

# Forgejo on k3s: create a private pull mirror of a GitHub repo with a short-lived admin-CLI token (done for diskos)

Context: the user asked to push diskOS to GitHub and to Forgejo. Forgejo runs on `moo@home` as a k3s deployment (`homelab` namespace: `forgejo-app`, `forgejo-db`; service `forgejo-app` is a LoadBalancer at `192.168.50.249`, web `:3500`, ssh `:2223`). There was no diskos repo there, my ssh key is not authorised on it (`Permission denied (publickey)`), and every existing repo under the user `samu` is a pull mirror of GitHub (`is_mirror = t`, interval 8 h, prune on). So the Forgejo side was done as a pull mirror of `github.com/txtsamu/diskos`, which the user chose from three options (mirror, normal repo plus push, skip). See [[homelab-vm-decommission-forgejo-kube-ovn-egress-bug]] for the stale Forgejo decoy on `homelab-vm`: use the k3s one on `home`.

## Steps and commands (all over `ssh moo@home`)

1. Find the deployment and service: `kubectl get deploy -A | grep -i forgejo`; `kubectl get svc -A | grep -i forgejo`.
2. Check there is no repo yet and learn the mirror convention (read only, through the database pod; put the SQL in a file and feed it on stdin, because quoting it inside `ssh '...'` broke on the `"user"` table name):
   ```bash
   ssh moo@home 'kubectl -n homelab exec -i deploy/forgejo-db -- sh -c "psql -U \$POSTGRES_USER -d \${POSTGRES_DB:-forgejo} -At"' < q.sql
   # q.sql: select r.id, u.name||'/'||r.name, r.is_private, r.is_mirror from repository r join "user" u on u.id=r.owner_id order by r.id;
   #        select m.repo_id, m.interval, m.enable_prune, r.original_url from mirror m join repository r on r.id=m.repo_id order by m.repo_id desc limit 3;
   ```
   The interval was 28800000000000 ns (8 h). The unauthenticated API search (`/api/v1/repos/search?q=diskos`) showed nothing because the repos are private.
3. Create a token with the admin CLI inside the app pod (it creates a credential, so it was deleted at the end), scoped to `write:repository`:
   `kubectl -n homelab exec deploy/forgejo-app -- [su-exec git] forgejo admin user generate-access-token --username samu --token-name tmp-diskos-mirror-20261112 --scopes write:repository --raw` (the script uses `su-exec git` only when the container user is root).
4. Create the mirror with the migrate API:
   ```bash
   curl -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" http://192.168.50.249:3500/api/v1/repos/migrate \
     -d '{"clone_addr":"https://github.com/txtsamu/diskos.git","repo_name":"diskos","repo_owner":"samu","service":"git","mirror":true,"private":true,"mirror_interval":"8h0m0s","description":"..."}'
   ```
   Result: HTTP 201, `samu/diskos`, private, mirror, clone URL `https://git.ssamu.id/samu/diskos.git`.
5. Revoke the token. The token-delete API needs basic auth, so the script deleted the single row I created: `delete from access_token where name='tmp-diskos-mirror-20261112';` (psql printed `DELETE 1`; a later `select count(*) ... like 'tmp-diskos-mirror%'` returned 0). The script ran all of this in one `ssh moo@home 'bash -s' < forgejo_mirror.sh` with a `trap` that deletes the token even if the migrate call fails, and never printed the token.
6. Verify: `select r.name, r.status, r.is_empty, r.is_mirror, r.size from repository r where r.name='diskos';` gave `diskos|0|f|t|161856665` after about 25 s (status 0 = ready, not empty, about 162 MB).

The same recipe works for any other GitHub repo (swap `clone_addr` and `repo_name`; private GitHub repos would need credentials in `clone_addr` or `auth_token`, which this one did not).

## Time estimate

About 3 minutes total (measured: the migrate call and the 25 s wait for the clone dominated; finding the deployment and the mirror convention took the rest).

## References

No external sources were used; the endpoints are Forgejo's own `/api/v1` (the instance serves its swagger at `/api/swagger`).
