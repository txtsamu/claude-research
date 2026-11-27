---
type: troubleshooting
tags: [android, vpnservice, vpn, jsch, ssh, direct-tcpip, ipv6, leak, foreground-service, kotlin, gradle, ndk, cloudflared, multi-profile]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Android VPN said "connected" but traffic still left from the phone's own network

**Repo:** private Android app `vpn-samu` (Kotlin, targetSdk 35, arm64 only)
**Commit:** `1359ea1` on `main`, on top of `be2812f`
**Build:** Gradle 8.9 + AGP 8.7.3 + JDK 21, SDK 35, NDK 27.0.12077973, on Fedora

The app builds a TUN with `VpnService`, hands it to `hev-socks5-tunnel`, and feeds a local SOCKS5
server that forwards each TCP connection over SSH `direct-tcpip` (JSch) through `cloudflared access
tcp` to a remote host. DNS is relayed as DNS-over-TCP over the same SSH session.

Symptom: pages loaded and DNS resolved through the remote host, but any "what is my IP" page showed
the phone's own address. Manual SOCKS tests to the remote host's port 22 either hung or returned
SOCKS reply `05`. An earlier session had written the symptom down as an unsolved "TCP does not exit
via the host" issue and never read the diagnostic log.

## Time estimate

| Step | Wall clock | Kind |
|---|---|---|
| Clone + read code, JSch source | ~10 min | estimate |
| Install JDK 21 / SDK / NDK / Gradle (already had JDK) | 27 s | measured (log markers) |
| Build `libcloudflared.so` (Go 1.27.4 + cgo, NDK clang) | 15 s | measured (log markers) |
| First `assembleDebug` (downloads AGP, AndroidX) | 58 s | measured |
| Incremental rebuild after edits | 7-10 s | measured |
| JSch repro + fix verification | ~5 min | estimate |

Total session: roughly 35 minutes. The toolchain downloads were fast because this machine sits on a
fast link; on a slow one, expect 10-20 minutes for the SDK + NDK alone.

## Root causes, in order of impact

### 1. IPv6 was never captured (the actual leak)

The TUN was built with only an IPv4 address and route:

```kotlin
.addAddress("10.8.0.2", 24)
.addRoute("0.0.0.0", 0)
```

A `VpnService` only owns the address families it adds routes for. Adding an IPv4 default route does
not stop IPv6 traffic; on a network that hands out a global IPv6 address, every AAAA-capable
destination keeps using the phone's own connection. That is a silent leak with exactly this
signature: browsing works, DNS works, and the reported public address is the carrier's.

Fix: also add;

```kotlin
.addAddress("fd00:8::2", 64)
.addRoute("::", 0)
```

`hev-socks5-tunnel` already handles IPv6 (lwIP built with `LWIP_IPV6`, netif listening with
`IPADDR_TYPE_ANY`), so no native change was needed. The SOCKS server already parsed `ATYP=4` and
passed the IPv6 literal to JSch, whose server-side `sshd` makes the real connection.

### 2. No foreground service, so Android killed the tunnel

`ArmVpnService` was a plain started service. Since Android 8, a background service is stopped soon
after the app leaves the foreground, which tears the TUN down. The UI kept showing "Connected"
because the process that would have updated it was gone too.

Fix: run as a foreground service with a status notification and a Disconnect action. The
`foregroundServiceType` is `systemExempted` (what Tailscale uses for its VPN service), with
`FOREGROUND_SERVICE_SYSTEM_EXEMPTED` and `POST_NOTIFICATIONS` declared.

### 3. JSch streams were taken in the wrong order (why CONNECT went silent)

`SocksServer` called `ChannelDirectTCPIP.connect()` first and `getInputStream()` after. In JSch,
`getInputStream()` is what installs the pipe that incoming channel data is written into
(`io.out`). Anything the server sends before that call goes to a null stream, the data packet
handler disconnects the channel, and the SOCKS client sees a connection that opened and then went
silent. JSch even logs it:

```
getInputStream() should be called before connect()
```

The server's *first flight* is what gets lost. That breaks server-speaks-first protocols (SSH,
SMTP, FTP, MySQL) and is invisible for HTTP, where the client speaks first. It explains why the
manual `CONNECT <host>:22` test hung while browsing mostly worked.

Reproduced without a phone, against a throwaway `sshd` on `127.0.0.1:2222` and JSch 0.2.21,
destination `127.0.0.1:22` (sends its banner immediately):

```java
ch.setHost("127.0.0.1"); ch.setPort(22);
ch.connect(10000);
Thread.sleep(delay);
InputStream in = ch.getInputStream();
// read with a 3 s timeout
```

Result, repeated with `delay` = 0, 1, 5, 20, 50 ms:

```
[jsch] getInputStream() should be called before connect()
banner bytes: NONE (timed out)
```

Same code, `getInputStream()` before `connect()`:

```
banner bytes: 22 -> SSH-2.0-OpenSSH_10.0
```

Fix: get both streams before `connect()`.

### 4. Small correctness fixes that removed the rest of the flakiness

- `connect()` only sends the channel-open request; it does not wait for confirmation. The old code
  replied `05 00` (success) immediately. Now it waits for `isConnected()`, fails fast on
  `isClosed`, and maps failures to real SOCKS codes (3/4/5/1).
- A dead SSH session is now replaced on the first channel-open failure instead of being reused.
- SOCKS channels are closed in `finally`, and the upstream pump no longer outlives the request.
- cloudflared is watched every 5 s; if the child exits, the VPN tears down with a reason instead of
  pretending to be connected.
- `files/diag.log` rotates per connection (previous one kept as `diag.log.old`) and now contains
  every cloudflared line plus each channel result with the server's reason code.

## Multi-profile

Added because the app was hard-wired to one target:

- `VpnProfile`: id, name, Access hostname, SSH user, private key, public key, service token, ports.
- `ProfileStore`: JSON list + active id in `vpn_profiles`, with a one-time migration of the old
  single-profile `arm_vpn` prefs into a "Default" profile.
- `ProfilesActivity`: list, tap to activate, per-row edit, new-profile button.
- `SettingsActivity`: per-profile editor (name, host, user, key, pubkey, token) plus delete.
- `ArmVpnService` takes `EXTRA_PROFILE_ID`; starting it with a different profile while connected
  reconnects. Switching the active profile while connected also reconnects from `onResume`.

## Exact build commands

```bash
git clone git@github.com:<user>/vpn-samu.git ~/vpn-samu
cd ~/vpn-samu

cp app/src/main/java/id/btech/armvpn/BuiltInKey.kt.template \
   app/src/main/java/id/btech/armvpn/BuiltInKey.kt   # paste the real private key
echo "sdk.dir=$HOME/android-sdk" > local.properties

git clone --recursive https://github.com/heiher/hev-socks5-tunnel \
   app/src/main/cpp/hev-socks5-tunnel
```

Toolchain (versions pinned by the project):

```bash
# JDK 21 is required; 17 and 25 do not match jvmToolchain(21)
sdkmanager --sdk_root="$HOME/android-sdk" \
  "platform-tools" "platforms;android-35" "build-tools;35.0.0" "ndk;27.0.12077973"
# Gradle 8.9 (no wrapper in the repo)
curl -sSLo g.zip https://services.gradle.org/distributions/gradle-8.9-bin.zip
unzip -q g.zip -d "$HOME/gradle"
```

cloudflared for Android arm64. cgo against the NDK is mandatory: the official Go static resolver
fails DNS on Android.

```bash
NDK=$HOME/android-sdk/ndk/27.0.12077973
CC=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang \
CGO_ENABLED=1 GOOS=android GOARCH=arm64 \
  go build -trimpath -ldflags "-s -w" \
  -o app/src/main/jniLibs/arm64-v8a/libcloudflared.so ./cmd/cloudflared
```

Build:

```bash
JAVA_HOME=/usr/lib/jvm/java-21-openjdk ANDROID_HOME=$HOME/android-sdk \
  ~/gradle/gradle-8.9/bin/gradle --no-daemon assembleDebug
```

Output and verification:

```bash
unzip -l app/build/outputs/apk/debug/app-debug.apk | grep lib/
# lib/arm64-v8a/libcloudflared.so       29178424
# lib/arm64-v8a/libhev-socks5-tunnel.so   549776

aapt2 dump xmltree --file AndroidManifest.xml app/build/outputs/apk/debug/app-debug.apk \
  | grep -E "foregroundServiceType|extractNativeLibs"
# foregroundServiceType=0x400   (systemExempted)
# extractNativeLibs=true
```

## Gotchas

- **`libcloudflared.so` and the hev source are git-ignored.** A fresh clone builds an APK that
  compiles cleanly and then fails at runtime with `libcloudflared.so missing`. The file has to be
  built and dropped into `app/src/main/jniLibs/arm64-v8a/` before installing.
- **The binary must be named `*.so`** and `useLegacyPackaging = true` (which sets
  `extractNativeLibs=true`) so Android extracts it executable into `nativeLibraryDir`.
- **`import android.widget.TextView`** etc. aside, the Kotlin compiler is quiet but the *JSch*
  warning is the only runtime hint you get for the stream-order bug. It goes to the app's log, which
  some OEM builds filter, so mirror it into a file (the app now does).
- **`aapt2 dump xmltree` on the built APK is the fast way** to confirm `foregroundServiceType` and
  that both native libs are packaged, without installing anything.
- **Do not trust `Channel.connect()` returning** as proof the channel opened: it only sends the
  request. Check `isConnected()`; on a refused destination JSch sets `isClosed` and
  `getExitStatus()` holds the reason.

## Not verified

No phone was attached to this machine, so the on-device behaviour is unverified:

- that the IPv6 route actually prevents the leak on a carrier with IPv6,
- that the foreground service survives backgrounding on the target OEM ROM,
- the multi-profile UI and the reconnect-on-switch path,
- end-to-end egress through the new host.

The check to run on the phone is the rotating log:

```bash
adb shell run-as id.btech.armvpn cat files/diag.log
```

It prints cloudflared's output, each channel open/failure with the server's reason code, and the
teardown reason.

Related: [[android-phone-proxy-via-vpz]], [[mikrotik-openvpn-warp-relay-bypass-isp-udp-block]].

## References

- JSch 0.2.21 sources (the `Channel.getInputStream()` warning and `ChannelDirectTCPIP.connect()`):
  <https://repo1.maven.org/maven2/com/github/mwiede/jsch/0.2.21/jsch-0.2.21-sources.jar>
- JSch `Channel.java` (current master): <https://github.com/mwiede/jsch/blob/master/src/main/java/com/jcraft/jsch/Channel.java>
- Android `VpnService.Builder` (routes, addresses, `addDisallowedApplication`):
  <https://developer.android.com/reference/android/net/VpnService.Builder>
- Android foreground service types (`systemExempted`, required permissions):
  <https://developer.android.com/develop/background-work/services/fgs/service-types>
- Tailscale Android manifest, used as the reference for a VPN app's `systemExempted` service:
  <https://github.com/tailscale/tailscale-android/blob/main/android/src/main/AndroidManifest.xml>
- hev-socks5-tunnel (config, lwIP IPv6, JNI entry point):
  <https://github.com/heiher/hev-socks5-tunnel>
- cloudflared (the `access tcp` subcommand and Go DNS resolver on Android):
  <https://github.com/cloudflare/cloudflared>
