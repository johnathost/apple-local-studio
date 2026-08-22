#!/usr/bin/env bash

# Local Apple Studio — single entry point
# Version: v5.1.0
#   Backend: service account + venv (Metal / mflux) on 127.0.0.1:8090
#            jailed with sandbox-exec (no /Users, no outbound net)
#   Frontend: Docker UI on 127.0.0.1:8080  (always as the login user)
#             read-only, cap-drop ALL, no-masquerade network, tmpfs /data

set -euo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT="$SCRIPT_DIR"
readonly FRONTEND_DIR="${ROOT}/frontend"
readonly BACKEND_DIR="${ROOT}/backend"

# macOS service account. Owns Metal, venv, HF cache, and data so the
# generation process cannot read the login user's home.
# Not used for Docker — Docker Desktop only talks to the login user.
readonly SERVICE_ACCOUNT="ivoai"
readonly HOMEDIR="/opt/${SERVICE_ACCOUNT}"
readonly APP_DIR="${HOMEDIR}/studio"
readonly LORA_DIR="${HOMEDIR}/lora"
readonly MODELS_DIR="${HOMEDIR}/models"
readonly MODEL_REPO="${MODEL_REPO:-mlx-community/FLUX.2-klein-9B}"
readonly MODEL_DIR="${MODELS_DIR}/FLUX.2-klein-9B"
readonly VENV_DIR="${HOMEDIR}/venv"
readonly BACKEND_PYTHON="${VENV_DIR}/bin/python"
readonly BACKEND_PIP="${VENV_DIR}/bin/pip"
readonly BACKEND_PID="${HOMEDIR}/backend.pid"
readonly BACKEND_LOG="${HOMEDIR}/backend.log"
readonly TMP_DIR="${HOMEDIR}/tmp"
readonly SECRET_FILE="${HOMEDIR}/.studio-secret"
readonly HF_HOME_DIR="${HOMEDIR}/.cache/huggingface"

readonly BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
readonly BACKEND_PORT="${BACKEND_PORT:-8090}"

readonly FRONTEND_IMAGE="${FRONTEND_IMAGE:-local-apple-studio-frontend:latest}"
readonly FRONTEND_CONTAINER="${FRONTEND_CONTAINER:-las-studio-frontend}"
readonly FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-8080}"
readonly FRONTEND_NETWORK="${FRONTEND_NETWORK:-las-studio}"
readonly SANDBOX_PROFILE="${APP_DIR}/backend/sandbox.sb"
readonly SANDBOX_EXEC="/usr/bin/sandbox-exec"

readonly FRONTEND_URL="http://127.0.0.1:${FRONTEND_HOST_PORT}"
readonly BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

# Login user who owns the repo + Docker Desktop session.
readonly LOGIN_USER="${SUDO_USER:-$(id -un)}"

readonly LOG_FILE="${ROOT}/install.log"
readonly LOCK_DIR="${TMP_DIR}/launcher.lock.d"

if [[ -x "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" ]]; then
	readonly PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
else
	readonly PYTHON_BIN="$(command -v python3 || true)"
fi

# -----------------------------------
# Logging
# -----------------------------------

setup_logging() {
	touch "$LOG_FILE" && chmod 644 "$LOG_FILE" || true
	if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" ]]; then
		chown "${SUDO_USER}:staff" "$LOG_FILE" 2>/dev/null || true
	fi
}

log() {
	# Always stderr so command substitutions (Finder paths, etc.) stay clean.
	local level="$1"
	shift
	local message="$*"
	local timestamp
	timestamp=$(date '+%Y-%m-%d %H:%M:%S')
	if [[ -t 2 ]]; then
		case "$level" in
			INFO)  printf "\033[1;36m%s [INFO] %s\033[0m\n" "$timestamp" "$message" ;;
			WARN)  printf "\033[1;33m%s [WARN] %s\033[0m\n" "$timestamp" "$message" ;;
			ERROR) printf "\033[1;31m%s [ERROR] %s\033[0m\n" "$timestamp" "$message" ;;
			*)     printf "%s [%s] %s\n" "$timestamp" "$level" "$message" ;;
		esac
	else
		printf "%s [%s] %s\n" "$timestamp" "$level" "$message"
	fi | tee -a "$LOG_FILE" >&2
}

run_command() {
	log INFO "Executing: $*"
	local output status
	set +e
	output=$("$@" 2>&1)
	status=$?
	set -e
	if [[ $status -eq 0 ]]; then
		log INFO "Success: $*"
		return 0
	fi
	log ERROR "Failed (exit code ${status}): $*"
	echo "$output" | sed 's/^/   | /' | tee -a "$LOG_FILE"
	return "$status"
}

# -----------------------------------
# Privilege split
#   service account → sudo (dscl, /opt, backend)
#   Docker        → login user (Docker Desktop socket)
# -----------------------------------

as_root() {
	if [[ $EUID -eq 0 ]]; then
		"$@"
	else
		sudo "$@"
	fi
}

as_service_account() {
	# sudo -u inherits the caller's cwd. ivoai cannot getcwd() under /Users,
	# and bash prints shell-init errors before a `bash -c 'cd ...'` can run.
	# cd in this process first (subshell) so the child starts in a readable dir.
	local cwd="/"
	if [[ -d "$HOMEDIR" ]]; then
		cwd="$HOMEDIR"
	fi
	(
		cd "$cwd" 2>/dev/null || cd /
		sudo -u "$SERVICE_ACCOUNT" -H "$@"
	)
}

# Docker Desktop is a per-login-user daemon. Never call docker as root.
docker_cli() {
	if [[ $EUID -eq 0 ]]; then
		sudo -u "$LOGIN_USER" -H docker "$@"
	else
		docker "$@"
	fi
}

release_lock() {
	as_service_account rm -rf "$LOCK_DIR" 2>/dev/null || as_root rm -rf "$LOCK_DIR" 2>/dev/null || true
}

# Lock lives under the service account tmp (not /tmp). Skipped until ivoai exists.
acquire_lock() {
	if ! id "$SERVICE_ACCOUNT" &>/dev/null || [[ ! -d "$HOMEDIR" ]]; then
		return 0
	fi
	if [[ ! -d "$TMP_DIR" ]]; then
		as_root mkdir -p "$TMP_DIR"
		chown_service "$TMP_DIR"
		as_root chmod 700 "$TMP_DIR"
	fi
	if ! as_service_account mkdir "$LOCK_DIR" 2>/dev/null; then
		echo "ERROR: Another launcher instance is running." >&2
		exit 1
	fi
	trap release_lock EXIT
}

# -----------------------------------
# Checks
# -----------------------------------

detect_os() {
	if [[ "$(uname -s)" != "Darwin" ]] || [[ "$(uname -m)" != "arm64" ]]; then
		log ERROR "Host backend requires macOS on Apple Silicon (Metal / mflux)."
		exit 1
	fi
	if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
		log ERROR "python3 not found."
		exit 1
	fi
}

need_sudo() {
	if ! sudo -n true 2>/dev/null; then
		log INFO "Service account requires sudo (${SERVICE_ACCOUNT}, home ${HOMEDIR})."
	fi
	if ! sudo -v; then
		log ERROR "sudo is required to manage the ${SERVICE_ACCOUNT} service account."
		exit 1
	fi
}

docker_ready() {
	command -v docker >/dev/null 2>&1 && docker_cli info >/dev/null 2>&1
}

need_docker() {
	if ! command -v docker >/dev/null 2>&1; then
		log ERROR "docker not found. Install Docker Desktop for Mac."
		exit 1
	fi
	if ! docker_cli info >/dev/null 2>&1; then
		log ERROR "Docker daemon not running. Start Docker Desktop (as ${LOGIN_USER})."
		exit 1
	fi
}

# -----------------------------------
# Host data dirs: LoRA weights + base model only (service account home).
# Uploads and generated images stay inside the frontend container.
# -----------------------------------

_gid_in_use() {
	dscl . -list /Groups PrimaryGroupID 2>/dev/null | awk '{print $2}' | grep -qx "$1"
}

# chown as ivoai using the numeric GID so a missing group *name* cannot fail.
# No arrays: macOS /bin/bash 3.2 + set -u treats empty "${arr[@]}" as unbound.
chown_service() {
	local recursive=""
	if [[ "${1:-}" == "-R" ]]; then
		recursive="-R"
		shift
	fi
	local gid
	gid="$(id -g "$SERVICE_ACCOUNT" 2>/dev/null || true)"
	if [[ -z "$gid" ]]; then
		log ERROR "Service account ${SERVICE_ACCOUNT} is missing."
		exit 1
	fi
	if [[ -n "$recursive" ]]; then
		as_root chown -R "${SERVICE_ACCOUNT}:${gid}" "$@"
	else
		as_root chown "${SERVICE_ACCOUNT}:${gid}" "$@"
	fi
}

_ensure_service_group() {
	if dscl . -read "/Groups/${SERVICE_ACCOUNT}" &>/dev/null; then
		return 0
	fi
	local gid next_id
	gid="$(id -g "$SERVICE_ACCOUNT" 2>/dev/null || true)"
	if [[ -z "$gid" ]]; then
		return 1
	fi
	if _gid_in_use "$gid"; then
		next_id=250
		while id -u "$next_id" &>/dev/null 2>&1 || _gid_in_use "$next_id"; do
			next_id=$((next_id + 1))
		done
		gid="$next_id"
		log INFO "Creating group ${SERVICE_ACCOUNT} (GID ${gid}) and retargeting the user."
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" PrimaryGroupID "$gid"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" RealName "Local Apple Studio"
		run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" PrimaryGroupID "$gid"
	else
		log INFO "Creating missing group ${SERVICE_ACCOUNT} (GID ${gid})."
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" PrimaryGroupID "$gid"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" RealName "Local Apple Studio"
	fi
}

ensure_shared_dirs() {
	if [[ -d "$LORA_DIR" && -d "$MODELS_DIR" ]]; then
		return 0
	fi
	need_sudo
	log INFO "Creating data dirs under ${HOMEDIR}"
	as_root mkdir -p "$LORA_DIR" "$MODELS_DIR"
	as_root chmod 755 "$HOMEDIR"
	as_root chmod 750 "$LORA_DIR" "$MODELS_DIR"
	if id "$SERVICE_ACCOUNT" &>/dev/null; then
		chown_service "$LORA_DIR" "$MODELS_DIR"
	fi
}

ensure_backend_secret() {
	if as_root test -s "$SECRET_FILE" 2>/dev/null; then
		return 0
	fi
	if ! id "$SERVICE_ACCOUNT" &>/dev/null; then
		log ERROR "Service account missing — deploy the backend before the frontend."
		exit 1
	fi
	need_sudo
	local secret
	secret="$(openssl rand -hex 32)"
	printf '%s\n' "$secret" | as_root tee "$SECRET_FILE" >/dev/null
	chown_service "$SECRET_FILE"
	as_root chmod 600 "$SECRET_FILE"
	log INFO "Backend secret written to ${SECRET_FILE}"
}

read_backend_secret() {
	as_root cat "$SECRET_FILE" 2>/dev/null || true
}

# -----------------------------------
# Service account + profile
# -----------------------------------

create_service_account() {
	if id "$SERVICE_ACCOUNT" &>/dev/null; then
		log INFO "Service account ${SERVICE_ACCOUNT} already exists."
		_ensure_service_group
		return 0
	fi

	log INFO "Creating service account ${SERVICE_ACCOUNT} (group ${SERVICE_ACCOUNT})."

	# UID under 500: not a login person.
	local next_id=250
	while id -u "$next_id" &>/dev/null 2>&1 || _gid_in_use "$next_id"; do
		next_id=$((next_id + 1))
	done

	if ! dscl . -read "/Groups/${SERVICE_ACCOUNT}" &>/dev/null; then
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" PrimaryGroupID "$next_id"
		run_command as_root dscl . -create "/Groups/${SERVICE_ACCOUNT}" RealName "Local Apple Studio"
	fi

	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}"
	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" UserShell /usr/bin/false
	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" RealName "Local Apple Studio"
	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" UniqueID "$next_id"
	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" PrimaryGroupID "$next_id"
	run_command as_root dscl . -create "/Users/${SERVICE_ACCOUNT}" NFSHomeDirectory "$HOMEDIR"

	run_command as_root mkdir -p "$HOMEDIR"
	chown_service -R "$HOMEDIR"
	# 755 so the login user can read backend logs / pid; data dirs are 750 below.
	run_command as_root chmod 755 "$HOMEDIR"

	log INFO "Service account ${SERVICE_ACCOUNT} created (UID/GID ${next_id}, home ${HOMEDIR}, shell /usr/bin/false)."
}

setup_profile() {
	log INFO "Configuring caches and runtime dirs under ${HOMEDIR}."

	as_root mkdir -p \
		"${HF_HOME_DIR}" \
		"${APP_DIR}" \
		"${HOMEDIR}/.cache" \
		"${HOMEDIR}/Library/Caches" \
		"$TMP_DIR" \
		"$LORA_DIR" \
		"$MODELS_DIR"

	chown_service -R "$HOMEDIR"
	as_root chmod 755 "$HOMEDIR"
	as_root chmod 750 "$LORA_DIR" "$MODELS_DIR" "$APP_DIR"
	as_root chmod 700 "${HOMEDIR}/.cache" "$TMP_DIR"

	ensure_backend_secret

	local bashrc="${HOMEDIR}/.bashrc"
	as_root tee "$bashrc" >/dev/null << EOF
# Local Apple Studio service account environment
export HOME="${HOMEDIR}"
export XDG_CACHE_HOME="${HOMEDIR}/.cache"

# Hugging Face / mflux — offline only. Missing local weights must fail closed.
export HF_HOME="${HF_HOME_DIR}"
export HF_HUB_CACHE="${HF_HOME_DIR}"
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# Studio: backend code under ${APP_DIR}, data under ${HOMEDIR}
export STUDIO_FRONTEND="${APP_DIR}"
export STUDIO_DATA_HOME="${HOMEDIR}"
export STUDIO_LORA_DIR="${LORA_DIR}"
export STUDIO_MODEL_DIR="${MODEL_DIR}"
export STUDIO_TMP_DIR="${TMP_DIR}"
export TMPDIR="${TMP_DIR}"
export TMP="${TMP_DIR}"
export STUDIO_BACKEND_SECRET="\$(cat '${SECRET_FILE}')"
export PYTHONPATH="${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
export BACKEND_HOST="${BACKEND_HOST}"
export BACKEND_PORT="${BACKEND_PORT}"

# MLX / Metal friendliness on unified memory
export KMP_DUPLICATE_LIB_OK=TRUE
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
EOF

	chown_service "$bashrc"
	as_root chmod 600 "$bashrc"

	log INFO "Service account environment configured."
}

sync_backend_code() {
	log INFO "Syncing backend code ${ROOT}/{frontend/src,backend} → ${APP_DIR}"
	as_root mkdir -p "${APP_DIR}/src" "${APP_DIR}/backend"
	as_root rsync -a --delete \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		"${FRONTEND_DIR}/src/" "${APP_DIR}/src/"
	as_root rsync -a --delete \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		"${BACKEND_DIR}/" "${APP_DIR}/backend/"
	# Rewrite Seatbelt placeholders so the jail matches this install.
	if [[ ! -f "${BACKEND_DIR}/sandbox.sb" ]]; then
		log ERROR "Repo is missing ${BACKEND_DIR}/sandbox.sb"
		exit 1
	fi
	as_root sed \
		-e "s|__DATA_HOME__|${HOMEDIR}|g" \
		-e "s|__BACKEND_PORT__|${BACKEND_PORT}|g" \
		"${BACKEND_DIR}/sandbox.sb" | as_root tee "$SANDBOX_PROFILE" >/dev/null
	chown_service -R "$APP_DIR"
	as_root chmod 750 "$APP_DIR"
	if as_root test -f "$SANDBOX_PROFILE"; then
		as_root chmod 640 "$SANDBOX_PROFILE"
	else
		log ERROR "Failed to write Seatbelt profile at ${SANDBOX_PROFILE}"
		exit 1
	fi
}

# -----------------------------------
# Host backend
# -----------------------------------

_backend_pid() {
	as_root cat "$BACKEND_PID" 2>/dev/null | tr -cd '0-9' || true
}

backend_running() {
	local pid
	pid="$(_backend_pid)"
	if [[ -n "$pid" ]] && as_root kill -0 "$pid" 2>/dev/null; then
		return 0
	fi
	as_root pgrep -u "$SERVICE_ACCOUNT" -f "backend.server" >/dev/null 2>&1
}

backend_venv_ready() {
	# venv is 750 ivoai — the login user cannot -x it.
	as_root test -x "$BACKEND_PYTHON"
}

deploy_backend() {
	detect_os
	need_sudo
	create_service_account
	setup_profile
	sync_backend_code

	log INFO "Creating backend venv at ${VENV_DIR}"
	if ! as_root test -d "$VENV_DIR"; then
		run_command as_service_account "$PYTHON_BIN" -m venv "$VENV_DIR"
		run_command as_service_account "$BACKEND_PYTHON" -m ensurepip --upgrade --default-pip || true
	fi
	run_command as_service_account "$BACKEND_PIP" install --upgrade pip
	run_command as_service_account "$BACKEND_PIP" install --upgrade -r "${APP_DIR}/backend/requirements.txt"
	as_root chmod 750 "$VENV_DIR"
	log INFO "Backend dependencies installed."
}

start_backend() {
	detect_os
	need_sudo
	ensure_shared_dirs

	if ! id "$SERVICE_ACCOUNT" &>/dev/null || ! backend_venv_ready; then
		log INFO "Service account / venv missing — deploying host backend first."
		deploy_backend
	else
		sync_backend_code
	fi

	if backend_running; then
		log WARN "Backend already running (PID $(_backend_pid)) @ ${BACKEND_URL}"
		return 0
	fi

	if [[ ! -x "$SANDBOX_EXEC" ]]; then
		log ERROR "sandbox-exec not found at ${SANDBOX_EXEC}; refusing to start an unsandboxed backend."
		exit 1
	fi
	if ! as_root test -f "$SANDBOX_PROFILE"; then
		log ERROR "Seatbelt profile missing at ${SANDBOX_PROFILE}. Re-run --deploy."
		exit 1
	fi

	as_root touch "$BACKEND_LOG" "$BACKEND_PID"
	chown_service "$BACKEND_LOG" "$BACKEND_PID"
	as_root chmod 644 "$BACKEND_LOG" "$BACKEND_PID"

	# Fail fast on a bad Seatbelt profile (errors used to vanish into /dev/null).
	local probe probe_status
	set +e
	probe="$(
		cd "$HOMEDIR" 2>/dev/null || cd /
		sudo -u "$SERVICE_ACCOUNT" -H "$SANDBOX_EXEC" -p '(version 1)(allow default)' /usr/bin/true 2>&1
	)"
	probe_status=$?
	set -e
	if [[ $probe_status -ne 0 ]]; then
		log ERROR "sandbox-exec cannot run even a trivial (allow default) profile (exit ${probe_status})."
		printf '%s\n' "$probe" | sed 's/^/   | /'
		exit 1
	fi

	set +e
	probe="$(
		cd "$HOMEDIR" 2>/dev/null || cd /
		sudo -u "$SERVICE_ACCOUNT" -H "$SANDBOX_EXEC" -f "$SANDBOX_PROFILE" /usr/bin/true 2>&1
	)"
	probe_status=$?
	set -e
	if [[ $probe_status -ne 0 ]]; then
		log ERROR "sandbox-exec rejected the jail profile (exit ${probe_status})."
		if [[ -n "$probe" ]]; then
			printf '%s\n' "$probe" | sed 's/^/   | /'
			printf '%s\n' "$probe" | as_root tee -a "$BACKEND_LOG" >/dev/null
		else
			log ERROR "No stderr (exit ${probe_status} = signal $((probe_status - 128)) )."
		fi
		log ERROR "Installed profile:"
		as_root cat "$SANDBOX_PROFILE" 2>/dev/null | sed 's/^/   | /' || true
		exit 1
	fi

	local starter="${TMP_DIR}/start-backend.sh"
	as_root tee "$starter" >/dev/null << EOF
#!/bin/bash
trap '' HUP
source "${HOMEDIR}/.bashrc" 2>/dev/null || true
export HOME="${HOMEDIR}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
cd "${APP_DIR}" || exit 1
exec >>"${BACKEND_LOG}" 2>&1 < /dev/null
echo \$\$ > "${BACKEND_PID}"
exec "${SANDBOX_EXEC}" -f "${SANDBOX_PROFILE}" "${BACKEND_PYTHON}" -m backend.server
EOF
	as_root chmod 700 "$starter"
	chown_service "$starter"

	log INFO "Starting sandboxed backend as ${SERVICE_ACCOUNT} on ${BACKEND_URL}"

	# Background sudo from this shell. nohup-inside-sudo on macOS dies with
	# "can't detach from console: Inappropriate ioctl for device".
	(
		cd "$HOMEDIR" 2>/dev/null || cd /
		trap '' HUP
		exec sudo -u "$SERVICE_ACCOUNT" -H /bin/bash "$starter"
	) &
	disown $! 2>/dev/null || true

	local i
	for i in 1 2 3 4 5 6 7 8; do
		sleep 1
		if backend_running; then
			log INFO "Backend started (PID $(_backend_pid))."
			return 0
		fi
	done

	log ERROR "Backend failed to start. Last log lines from ${BACKEND_LOG}:"
	as_root tail -n 40 "$BACKEND_LOG" 2>/dev/null | sed 's/^/   | /' || log WARN "No ${BACKEND_LOG} yet."
	log ERROR "ivoai processes:"
	as_root pgrep -lf -u "$SERVICE_ACCOUNT" 2>/dev/null | sed 's/^/   | /' || log WARN "none"
	exit 1
}

stop_backend() {
	if id "$SERVICE_ACCOUNT" &>/dev/null; then
		need_sudo
	fi

	local pid
	pid="$(_backend_pid)"
	if [[ -n "$pid" ]] && as_root kill -0 "$pid" 2>/dev/null; then
		log INFO "Stopping backend (PID ${pid})"
		as_root kill "$pid" 2>/dev/null || true
		local _
		for _ in 1 2 3 4 5; do
			as_root kill -0 "$pid" 2>/dev/null || break
			sleep 1
		done
		as_root kill -9 "$pid" 2>/dev/null || true
	fi
	as_root rm -f "$BACKEND_PID"
	if id "$SERVICE_ACCOUNT" &>/dev/null; then
		as_root pkill -u "$SERVICE_ACCOUNT" -f "backend.server" 2>/dev/null || true
	fi
	log INFO "Backend stopped."
}

# -----------------------------------
# Docker frontend (no compose) — login user only
# -----------------------------------

image_exists() {
	docker_cli image inspect "$FRONTEND_IMAGE" >/dev/null 2>&1
}

container_exists() {
	docker_cli container inspect "$FRONTEND_CONTAINER" >/dev/null 2>&1
}

container_running() {
	[[ "$(docker_cli inspect -f '{{.State.Running}}' "$FRONTEND_CONTAINER" 2>/dev/null || echo false)" == "true" ]]
}

container_image_id() {
	docker_cli inspect -f '{{.Image}}' "$FRONTEND_CONTAINER" 2>/dev/null || true
}

image_id() {
	docker_cli inspect -f '{{.Id}}' "$FRONTEND_IMAGE" 2>/dev/null || true
}

container_stale() {
	container_exists || return 1
	local cid iid
	cid="$(container_image_id)"
	iid="$(image_id)"
	[[ -n "$cid" && -n "$iid" && "$cid" != "$iid" ]]
}

remove_container() {
	if container_exists; then
		log INFO "Removing container ${FRONTEND_CONTAINER}"
		docker_cli rm -f "$FRONTEND_CONTAINER" >/dev/null
	fi
}

ensure_frontend_network() {
	if docker_cli network inspect "$FRONTEND_NETWORK" >/dev/null 2>&1; then
		return 0
	fi
	log INFO "Creating isolated frontend network ${FRONTEND_NETWORK} (no IP masquerade)"
	# No NAT → no internet. host.docker.internal is added per-container
	# (--add-host host-gateway). --dns 127.0.0.1 blocks public DNS; the
	# extra_hosts entry still works because it lands in /etc/hosts.
	docker_cli network create \
		--driver bridge \
		--opt com.docker.network.bridge.enable_ip_masquerade=false \
		--opt com.docker.network.bridge.enable_icc=false \
		"$FRONTEND_NETWORK" >/dev/null
}

container_unjailed() {
	container_exists || return 1
	local ro net extra
	ro="$(docker_cli inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$FRONTEND_CONTAINER" 2>/dev/null || echo false)"
	net="$(docker_cli inspect -f '{{.HostConfig.NetworkMode}}' "$FRONTEND_CONTAINER" 2>/dev/null || echo)"
	extra="$(docker_cli inspect -f '{{range .HostConfig.ExtraHosts}}{{.}} {{end}}' "$FRONTEND_CONTAINER" 2>/dev/null || true)"
	[[ "$ro" != "true" || "$net" != "$FRONTEND_NETWORK" || "$extra" != *host.docker.internal* ]]
}

create_container() {
	ensure_backend_secret
	ensure_frontend_network
	local secret
	secret="$(read_backend_secret)"
	if [[ -z "$secret" ]]; then
		log ERROR "Backend secret missing at ${SECRET_FILE}"
		exit 1
	fi
	log INFO "Creating jailed container ${FRONTEND_CONTAINER} from ${FRONTEND_IMAGE}"
	# uid 1000 matches Dockerfile `useradd --uid 1000 studio`.
	# /data is tmpfs: outputs die with the container (stop/restart/crash).
	docker_cli create \
		--name "$FRONTEND_CONTAINER" \
		--restart unless-stopped \
		--read-only \
		--cap-drop ALL \
		--security-opt no-new-privileges:true \
		--network "$FRONTEND_NETWORK" \
		--add-host=host.docker.internal:host-gateway \
		--dns 127.0.0.1 \
		--tmpfs /tmp:rw,nosuid,noexec,uid=1000,gid=1000,size=64m \
		--tmpfs /data:rw,nosuid,uid=1000,gid=1000,size=2g \
		-p "127.0.0.1:${FRONTEND_HOST_PORT}:8080" \
		-e "STUDIO_BACKEND_SECRET=${secret}" \
		"$FRONTEND_IMAGE" >/dev/null
}

ensure_container() {
	if container_stale || container_unjailed; then
		log INFO "Container is stale or missing jail flags — recreating."
		remove_container
	fi
	if ! container_exists; then
		create_container
	fi
}

deploy_frontend() {
	need_docker
	log INFO "Building Docker image ${FRONTEND_IMAGE}…"
	docker_cli build -t "$FRONTEND_IMAGE" "$FRONTEND_DIR"
	log INFO "Docker image ready."
	remove_container
	create_container
	log INFO "Frontend container created (${FRONTEND_CONTAINER})."
}

start_frontend() {
	need_docker

	if ! image_exists; then
		log INFO "Frontend image missing — building and creating the container."
		deploy_frontend
	else
		ensure_container
	fi

	if container_running; then
		log WARN "Frontend container already running."
		return 0
	fi

	log INFO "Starting frontend container…"
	docker_cli start "$FRONTEND_CONTAINER" >/dev/null
	log INFO "Frontend → ${FRONTEND_URL}"
}

stop_frontend() {
	if ! docker_ready; then
		return 0
	fi
	if container_running; then
		log INFO "Stopping frontend container…"
		docker_cli stop "$FRONTEND_CONTAINER" >/dev/null || true
	fi
	log INFO "Frontend container stopped."
}

# -----------------------------------
# Combined ops
# -----------------------------------

deploy_all() {
	log INFO "=== Deploy (service account + Docker frontend) ==="
	deploy_backend
	deploy_frontend
	log INFO "=== Deploy done ==="
	log INFO "Next: ./launcher.sh --start"
}

start_all() {
	log INFO "=== Starting stack ==="
	start_backend
	start_frontend
	sleep 2
	status_all
}

stop_all() {
	log INFO "=== Stopping stack ==="
	stop_frontend
	stop_backend
}

status_all() {
	echo
	if backend_running; then
		log INFO "Backend: running as ${SERVICE_ACCOUNT} (PID $(_backend_pid)) @ ${BACKEND_URL}"
		if command -v curl >/dev/null 2>&1; then
			local secret
			secret="$(read_backend_secret)"
			if [[ -n "$secret" ]]; then
				curl -fsS -H "Authorization: Bearer ${secret}" "${BACKEND_URL}/health" 2>/dev/null | tee -a "$LOG_FILE" || log WARN "Backend health failed"
			else
				curl -fsS "${BACKEND_URL}/health" 2>/dev/null | tee -a "$LOG_FILE" || log WARN "Backend health failed"
			fi
			echo
		fi
	else
		log WARN "Backend: not running"
	fi

	if docker_ready; then
		if container_running; then
			log INFO "Frontend: running @ ${FRONTEND_URL}"
			curl -fsS "${FRONTEND_URL}/api/health" 2>/dev/null | tee -a "$LOG_FILE" || log WARN "Frontend health failed"
			echo
		elif container_exists; then
			log WARN "Frontend container: created but stopped"
		elif image_exists; then
			log WARN "Frontend image built, container not created"
		else
			log WARN "Frontend: image not built"
		fi
	else
		log WARN "Docker not available for status"
	fi

	log INFO "Service account → ${SERVICE_ACCOUNT}  ${HOMEDIR}"
	if as_root test -f "$SANDBOX_PROFILE" && [[ -x "$SANDBOX_EXEC" ]]; then
		log INFO "Jail    → sandbox-exec ${SANDBOX_PROFILE}"
	else
		log WARN "Jail    → Seatbelt profile or sandbox-exec missing"
	fi
	log INFO "Venv    → ${VENV_DIR}"
	log INFO "LoRAs   → ${LORA_DIR}"
	if as_root test -f "${MODEL_DIR}/model_index.json" 2>/dev/null \
		|| as_root bash -c 'ls "$1"/*.safetensors "$1"/*/*.safetensors' _ "$MODEL_DIR" >/dev/null 2>&1; then
		log INFO "Model   → ${MODEL_DIR} (local, no Hugging Face)"
	else
		log WARN "Model   → missing. $0 --download-model   or   $0 --import-model DIR"
	fi
}

logs_all() {
	log INFO "Tailing backend + frontend logs (Ctrl+C to stop)."
	local tpid=""
	if [[ -f "$BACKEND_LOG" ]]; then
		tail -n 50 -f "$BACKEND_LOG" &
		tpid=$!
	else
		log WARN "No backend log yet at ${BACKEND_LOG}"
	fi
	if docker_ready && container_exists; then
		docker_cli logs -f --tail 50 "$FRONTEND_CONTAINER" || true
	else
		log WARN "Frontend container not available for logs."
		if [[ -n "$tpid" ]]; then
			wait "$tpid" || true
		fi
	fi
	if [[ -n "$tpid" ]]; then
		kill "$tpid" 2>/dev/null || true
	fi
}

need_zip_tools() {
	if ! command -v zip >/dev/null 2>&1 || ! command -v unzip >/dev/null 2>&1; then
		log ERROR "zip and unzip are required (macOS ships both in /usr/bin)."
		exit 1
	fi
}

_abs_user_path() {
	local dest="${1:-}"
	case "$dest" in
		~) dest="$(eval echo "~${LOGIN_USER}")" ;;
		~/*) dest="$(eval echo "~${LOGIN_USER}")/${dest#~/}" ;;
	esac
	if [[ "$dest" != /* ]]; then
		dest="$(pwd)/${dest}"
	fi
	printf '%s\n' "$dest"
}

# Finder panels must run as the login user (never root) so they appear on the desktop.
_run_osascript() {
	if ! command -v osascript >/dev/null 2>&1; then
		log ERROR "osascript not found. Finder dialogs require macOS."
		exit 1
	fi
	if [[ $EUID -eq 0 ]]; then
		sudo -u "$LOGIN_USER" -H osascript "$@"
	else
		osascript "$@"
	fi
}

_trim_osascript_path() {
	local path="$1"
	path="${path//$'\r'/}"
	# Last line that looks like an absolute path — never keep leaked log text.
	path="$(printf '%s\n' "$path" | awk '/^\// { p=$0 } END { print p }')"
	path="${path#"${path%%[![:space:]]*}"}"
	path="${path%"${path##*[![:space:]]}"}"
	printf '%s\n' "$path"
}

_finder_choose_zip() {
	local prompt="$1"
	local path status
	log INFO "Opening Finder: ${prompt}"
	set +e
	path="$(_run_osascript - "$prompt" <<'APPLESCRIPT'
on run argv
	set thePrompt to item 1 of argv
	tell application "Finder" to activate
	delay 0.15
	try
		set f to choose file with prompt thePrompt of type {"zip", "public.zip-archive"} without invisibles
		return POSIX path of f
	on error number -128
		return ""
	end try
end run
APPLESCRIPT
)"
	status=$?
	set -e
	path="$(_trim_osascript_path "$path")"
	if [[ $status -ne 0 ]]; then
		log ERROR "Could not open a Finder dialog. Use a logged-in macOS desktop session,"
		log ERROR "or pass a zip path on the command line."
		exit 1
	fi
	if [[ -z "$path" ]]; then
		log INFO "Canceled."
		exit 0
	fi
	printf '%s\n' "$path"
}

_finder_choose_save_zip() {
	local prompt="$1"
	local default_name="$2"
	local path status
	log INFO "Opening Finder: ${prompt}"
	set +e
	path="$(_run_osascript - "$prompt" "$default_name" <<'APPLESCRIPT'
on run argv
	set thePrompt to item 1 of argv
	set theDefault to item 2 of argv
	tell application "Finder" to activate
	delay 0.15
	try
		set f to choose file name with prompt thePrompt default name theDefault
		return POSIX path of f
	on error number -128
		return ""
	end try
end run
APPLESCRIPT
)"
	status=$?
	set -e
	path="$(_trim_osascript_path "$path")"
	if [[ $status -ne 0 ]]; then
		log ERROR "Could not open a Finder dialog. Use a logged-in macOS desktop session,"
		log ERROR "or pass a destination path on the command line."
		exit 1
	fi
	if [[ -z "$path" ]]; then
		log INFO "Canceled."
		exit 0
	fi
	printf '%s\n' "$path"
}

_require_zip_file() {
	local src="${1:-}"
	local prompt="$2"
	if [[ -z "$src" ]]; then
		src="$(_finder_choose_zip "$prompt")"
	fi
	src="$(_abs_user_path "$src")"
	if [[ ! -f "$src" ]]; then
		log ERROR "Expected a .zip file, not found: ${src}"
		exit 1
	fi
	case "$src" in
		*.zip|*.ZIP) ;;
		*)
			log ERROR "Expected a .zip file: ${src}"
			exit 1
			;;
	esac
	if ! unzip -Z1 "$src" >/dev/null 2>&1; then
		log ERROR "Not a valid zip archive: ${src}"
		exit 1
	fi
	printf '%s\n' "$src"
}

_assert_zip_safe() {
	local zip="$1"
	local py="${PYTHON_BIN:-python3}"
	if [[ -n "$py" && -x "$py" ]]; then
		if ! "$py" - "$zip" <<'PY'
import sys
import zipfile

path = sys.argv[1]
with zipfile.ZipFile(path) as zf:
    for name in zf.namelist():
        n = name.replace("\\", "/")
        if n.startswith("/") or n.startswith("../") or "/../" in f"/{n}/":
            sys.exit(f"refusing unsafe path in zip: {name}")
PY
		then
			log ERROR "Zip failed the path-safety check: ${zip}"
			exit 1
		fi
		return
	fi
	local name
	while IFS= read -r name; do
		[[ -z "$name" ]] && continue
		name="${name//\\//}"
		if [[ "$name" == /* || "$name" == ../* || "$name" == */../* || "$name" == */.. ]]; then
			log ERROR "refusing unsafe path in zip: ${name}"
			exit 1
		fi
	done <<UNZIP_LIST
$(unzip -Z1 "$zip")
UNZIP_LIST
}

_unzip_to() {
	local zip="$1"
	local dest="$2"
	_assert_zip_safe "$zip"
	as_root mkdir -p "$dest"
	as_root unzip -o -q "$zip" -d "$dest"
}

_first_dir_child() {
	as_root bash -c '
		only=""
		n=0
		for p in "$1"/*; do
			[ -e "$p" ] || continue
			if [ -d "$p" ]; then
				n=$((n + 1))
				only="$p"
			else
				exit 0
			fi
		done
		if [ "$n" -eq 1 ]; then
			printf "%s\n" "$only"
		fi
	' _ "$1"
}

_model_root_from_extracted() {
	local root="$1" child latest
	if _looks_like_model_dir "$root"; then
		printf '%s\n' "$root"
		return 0
	fi
	if as_root test -d "${root}/snapshots"; then
		latest="$(as_root bash -c 'ls -1td "$1"/snapshots/*/ 2>/dev/null | head -1' _ "$root" || true)"
		latest="${latest%/}"
		if [[ -n "$latest" ]] && _looks_like_model_dir "$latest"; then
			printf '%s\n' "$latest"
			return 0
		fi
	fi
	child="$(_first_dir_child "$root")"
	if [[ -n "$child" ]]; then
		_model_root_from_extracted "$child"
		return
	fi
	return 1
}

import_loras() {
	need_zip_tools
	local src
	src="$(_require_zip_file "${1:-}" "Select a LoRA zip to import")"
	ensure_shared_dirs
	need_sudo
	as_root mkdir -p "$TMP_DIR"
	as_root chmod 700 "$TMP_DIR"

	local staging
	staging="$(as_root mktemp -d "${TMP_DIR}/lora-import.XXXXXX")"
	log INFO "Unzipping LoRAs from ${src} → ${LORA_DIR}"
	if ! _unzip_to "$src" "$staging"; then
		as_root rm -rf "$staging"
		log ERROR "Failed to unzip ${src}"
		exit 1
	fi

	local count
	count="$(as_root bash -c 'find "$1" -type f -name "*.safetensors" | wc -l' _ "$staging" | tr -d "[:space:]")"
	if [[ -z "$count" || "$count" -eq 0 ]]; then
		as_root rm -rf "$staging"
		log ERROR "No .safetensors files in ${src}"
		exit 1
	fi

	as_root mkdir -p "$LORA_DIR"
	as_root bash -c '
		find "$1" -type f -name "*.safetensors" -print0 |
			while IFS= read -r -d "" f; do
				cp -f "$f" "$2/$(basename "$f")"
			done
	' _ "$staging" "$LORA_DIR"
	as_root rm -rf "$staging"
	chown_service -R "$LORA_DIR"
	as_root chmod 750 "$LORA_DIR"
	log INFO "Imported ${count} LoRA file(s) into ${LORA_DIR}"
	as_root ls -la "$LORA_DIR" | tee -a "$LOG_FILE"
}

# If DIR is a huggingface hub wrapper, use the newest snapshots/<hash>.
_resolve_model_src() {
	local src="$1"
	if [[ -d "${src}/snapshots" ]]; then
		local latest
		latest="$(ls -1td "${src}/snapshots"/*/ 2>/dev/null | head -1 || true)"
		if [[ -n "$latest" ]]; then
			printf '%s\n' "${latest%/}"
			return 0
		fi
	fi
	printf '%s\n' "$src"
}

_looks_like_model_dir() {
	local src="$1"
	as_root test -f "${src}/model_index.json" 2>/dev/null && return 0
	as_root bash -c 'ls "$1"/*.safetensors "$1"/*/*.safetensors' _ "$src" >/dev/null 2>&1 && return 0
	[[ -f "${src}/model_index.json" ]] && return 0
	ls "${src}"/*.safetensors >/dev/null 2>&1 && return 0
	ls "${src}"/*/*.safetensors >/dev/null 2>&1 && return 0
	return 1
}

_installed_model_dir() {
	local candidate resolved latest
	for candidate in "$MODEL_DIR" "${MODELS_DIR}/${MODEL_REPO##*/}" "${MODELS_DIR}/models--${MODEL_REPO//\//--}"; do
		resolved="$candidate"
		if as_root test -d "${candidate}/snapshots" 2>/dev/null; then
			latest="$(as_root bash -c 'ls -1td "$1"/snapshots/*/ 2>/dev/null | head -1' _ "$candidate" || true)"
			if [[ -n "$latest" ]]; then
				resolved="${latest%/}"
			fi
		fi
		if _looks_like_model_dir "$resolved"; then
			printf '%s\n' "$resolved"
			return 0
		fi
	done
	return 1
}

_ensure_hub_tooling() {
	create_service_account
	setup_profile
	if ! as_root test -x "$BACKEND_PYTHON"; then
		log INFO "Creating backend venv at ${VENV_DIR}"
		as_service_account "$PYTHON_BIN" -m venv "$VENV_DIR"
		as_service_account "$BACKEND_PYTHON" -m ensurepip --upgrade --default-pip || true
	fi
	run_command as_service_account "$BACKEND_PIP" install --upgrade "huggingface_hub>=0.26.0"
}

import_model() {
	need_zip_tools
	local src
	src="$(_require_zip_file "${1:-}" "Select a FLUX model zip to import")"
	ensure_shared_dirs
	need_sudo
	as_root mkdir -p "$TMP_DIR"
	as_root chmod 700 "$TMP_DIR"

	if backend_running; then
		log WARN "Stopping backend so weights are not replaced while loaded."
		stop_backend
	fi

	local staging
	staging="$(as_root mktemp -d "${TMP_DIR}/model-import.XXXXXX")"
	log INFO "Unzipping base model from ${src} → ${MODEL_DIR}"
	log INFO "This can take a while for a large snapshot — leave it running."
	if ! _unzip_to "$src" "$staging"; then
		as_root rm -rf "$staging"
		log ERROR "Failed to unzip ${src}"
		exit 1
	fi

	local extracted
	if ! extracted="$(_model_root_from_extracted "$staging")"; then
		as_root rm -rf "$staging"
		log ERROR "Zip is not a FLUX snapshot (no model_index.json / *.safetensors): ${src}"
		exit 1
	fi

	as_root mkdir -p "$MODEL_DIR"
	as_root rsync -a --delete --exclude '.cache/' --exclude '__pycache__/' "${extracted}/" "${MODEL_DIR}/"
	as_root rm -rf "$staging"
	chown_service -R "$MODEL_DIR"
	as_root chmod 750 "$MODEL_DIR"
	log INFO "Model ready at ${MODEL_DIR}"
	log INFO "Restart the backend so it picks up the local weights: $0 --restart"
}

download_model() {
	# One-shot operator fetch. Runtime generation stays offline / jailed.
	# The HF key is taken from the CLI argument only and is never written
	# to the service-account bashrc, env files, or the HF token cache.
	local token="${1:-}"
	token="${token//$'\n'/}"
	token="${token//$'\r'/}"
	token="${token#"${token%%[![:space:]]*}"}"
	token="${token%"${token##*[![:space:]]}"}"

	detect_os
	need_sudo
	_ensure_hub_tooling
	ensure_shared_dirs

	if backend_running; then
		log WARN "Stopping backend so weights are not replaced while loaded."
		stop_backend
	fi

	as_root mkdir -p "$MODEL_DIR" "$HF_HOME_DIR"
	chown_service "$MODEL_DIR" "$HF_HOME_DIR"
	as_root chmod 750 "$MODEL_DIR"

	local script="${TMP_DIR}/hf_snapshot.py"
	as_root tee "$script" >/dev/null <<'PY'
import os
import sys
from pathlib import Path

repo = os.environ["STUDIO_MODEL_REPO"]
dest = Path(os.environ["STUDIO_MODEL_DIR"])
dest.mkdir(parents=True, exist_ok=True)
token_file = os.environ.get("STUDIO_HF_TOKEN_FILE") or ""
token = None
if token_file:
    raw = Path(token_file).read_text(encoding="utf-8")
    token = raw.strip() or None

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("huggingface_hub is not installed in the backend venv", file=sys.stderr)
    sys.exit(1)

print(f"snapshot_download({repo!r} -> {dest})", flush=True)
kwargs = {"repo_id": repo, "local_dir": str(dest)}
if token:
    kwargs["token"] = token
try:
    snapshot_download(**kwargs)
except TypeError:
    snapshot_download(repo_id=repo, local_dir=str(dest))
print("download complete", flush=True)
PY
	chown_service "$script"
	as_root chmod 700 "$script"

	local token_file=""
	if [[ -n "$token" ]]; then
		token_file="${TMP_DIR}/hf_token.once"
		printf '%s\n' "$token" | as_root tee "$token_file" >/dev/null
		chown_service "$token_file"
		as_root chmod 600 "$token_file"
	fi

	log INFO "Downloading ${MODEL_REPO} → ${MODEL_DIR}"
	log INFO "This is a manual online fetch (tens of GB). Generation stays local/offline."
	if [[ -n "$token" ]]; then
		log INFO "Using the API key passed on the command line (not saved to ${SERVICE_ACCOUNT} or .bashrc)."
	else
		log INFO "No API key given. For a gated repo: $0 --download-model YOUR_HF_TOKEN"
	fi

	set +e
	as_service_account env \
		-u HF_HUB_OFFLINE \
		-u TRANSFORMERS_OFFLINE \
		-u HF_TOKEN \
		-u HUGGING_FACE_HUB_TOKEN \
		HOME="$HOMEDIR" \
		HF_HOME="$HF_HOME_DIR" \
		HF_HUB_CACHE="$HF_HOME_DIR" \
		HF_HUB_DISABLE_TELEMETRY=1 \
		STUDIO_MODEL_REPO="$MODEL_REPO" \
		STUDIO_MODEL_DIR="$MODEL_DIR" \
		STUDIO_HF_TOKEN_FILE="$token_file" \
		"$BACKEND_PYTHON" -u "$script"
	local status=$?
	set -e
	as_root rm -f "$script" "$token_file"
	# huggingface_hub must not leave a cached login on the service account.
	as_root rm -f \
		"${HF_HOME_DIR}/token" \
		"${HF_HOME_DIR}/stored_tokens" \
		"${HOMEDIR}/.huggingface/token" 2>/dev/null || true

	if [[ $status -ne 0 ]]; then
		log ERROR "Download failed (exit ${status}). Check network, disk space, or the API key."
		exit 1
	fi

	if ! _looks_like_model_dir "$MODEL_DIR"; then
		log ERROR "Download finished but ${MODEL_DIR} is not a FLUX snapshot."
		exit 1
	fi

	chown_service -R "$MODEL_DIR"
	as_root chmod 750 "$MODEL_DIR"
	log INFO "Model ready at ${MODEL_DIR}"
	log INFO "Runtime stays offline. Start with: $0 --start"
}

export_model() {
	need_zip_tools
	local dest="${1:-}"
	if [[ -z "$dest" ]]; then
		dest="$(_finder_choose_save_zip "Choose where to save the model zip" "FLUX.2-klein-9B.zip")"
	fi
	dest="$(_abs_user_path "$dest")"
	if [[ -d "$dest" || "$dest" == */ ]]; then
		dest="${dest%/}/FLUX.2-klein-9B.zip"
	else
		case "$dest" in
			*.zip|*.ZIP) ;;
			*) dest="${dest}.zip" ;;
		esac
	fi
	if [[ "$dest" == *$'\n'* || "$dest" == *$'\r'* || "$dest" != /* ]]; then
		log ERROR "Invalid export path (refusing leaked log text or a relative name)."
		exit 1
	fi

	need_sudo
	local src
	if ! src="$(_installed_model_dir)"; then
		log ERROR "No local model under ${MODELS_DIR}."
		log ERROR "Fetch one first:  $0 --download-model"
		log ERROR "Or import:        $0 --import-model /path/to/model.zip"
		exit 1
	fi

	local parent src_real dest_real
	parent="$(dirname "$dest")"
	as_root mkdir -p "$parent"
	src_real="$(as_root realpath "$src" 2>/dev/null || printf '%s' "$src")"
	dest_real="$(as_root realpath "$parent" 2>/dev/null || printf '%s' "$parent")"
	if [[ "$dest_real" == "$src_real" || "$dest_real" == "$src_real"/* ]]; then
		log ERROR "Refusing to write the zip inside the model directory: ${dest}"
		exit 1
	fi

	local src_size
	src_size="$(as_root du -sh "$src" 2>/dev/null | awk '{print $1}')"
	log INFO "Zipping ${src} (${src_size:-?}) → ${dest}"
	log INFO "Store only (no deflate) — safetensors are already compressed."
	as_root rm -f "$dest"

	local watch_pid=""
	(
		while sleep 3; do
			if as_root test -f "$dest"; then
				sz="$(as_root du -h "$dest" 2>/dev/null | awk '{print $1}')"
				log INFO "zip so far: ${sz} / ${src_size:-unknown} -> ${dest}"
			fi
		done
	) &
	watch_pid=$!

	local status=0
	set +e
	# -0: store. Default deflate on a 30–50 GB .safetensors looks frozen for minutes.
	as_root bash -c 'cd "$1" && zip -0 -r -y "$2" . -x "./.cache/*" "./__pycache__/*" "*.pyc"' _ "$src" "$dest"
	status=$?
	set -e
	kill "$watch_pid" 2>/dev/null || true
	wait "$watch_pid" 2>/dev/null || true

	if [[ $status -ne 0 ]]; then
		log ERROR "zip failed (exit ${status}). Partial file left at ${dest}"
		exit 1
	fi

	if ! as_root chown "${LOGIN_USER}:staff" "$dest" 2>/dev/null; then
		as_root chown "$LOGIN_USER" "$dest"
	fi
	as_root chmod 600 "$dest"
	log INFO "Exported zip to ${dest} ($(as_root du -h "$dest" 2>/dev/null | awk '{print $1}'))"
	log INFO "Re-import later with: $0 --import-model ${dest}"
}

uninstall_all() {
	log WARN "This stops the stack and purges:"
	log WARN "  • service account ${SERVICE_ACCOUNT} and ${HOMEDIR}"
	log WARN "    including lora/, models/, venv, and HF cache"
	log WARN "  • frontend container ${FRONTEND_CONTAINER} and image ${FRONTEND_IMAGE}"
	read -r -p "Type 'PURGE' to confirm: " confirm
	if [[ "$confirm" != "PURGE" ]]; then
		log INFO "Aborted."
		exit 0
	fi

	stop_all

	if docker_ready; then
		if container_exists; then
			log INFO "Removing container ${FRONTEND_CONTAINER}"
			docker_cli rm -f "$FRONTEND_CONTAINER" >/dev/null || true
		fi
		if image_exists; then
			log INFO "Removing image ${FRONTEND_IMAGE}"
			docker_cli rmi -f "$FRONTEND_IMAGE" || true
		fi
		if docker_cli network inspect "$FRONTEND_NETWORK" >/dev/null 2>&1; then
			log INFO "Removing network ${FRONTEND_NETWORK}"
			docker_cli network rm "$FRONTEND_NETWORK" >/dev/null || true
		fi
	else
		log WARN "Docker not running — skipped container/image removal. Start Docker and re-run --uninstall to finish."
	fi

	if id "$SERVICE_ACCOUNT" &>/dev/null; then
		need_sudo
		log INFO "Killing residual processes for ${SERVICE_ACCOUNT}"
		as_root pkill -u "$SERVICE_ACCOUNT" 2>/dev/null || true
		log INFO "Deleting service account ${SERVICE_ACCOUNT}"
		as_root dscl . -delete "/Users/${SERVICE_ACCOUNT}" 2>/dev/null || true
		if dscl . -read "/Groups/${SERVICE_ACCOUNT}" &>/dev/null; then
			log INFO "Deleting group ${SERVICE_ACCOUNT}"
			as_root dscl . -delete "/Groups/${SERVICE_ACCOUNT}" 2>/dev/null || true
		fi
	fi

	if [[ -d "$HOMEDIR" ]]; then
		need_sudo
		log INFO "Removing ${HOMEDIR}"
		as_root rm -rf "$HOMEDIR"
	fi

	rm -f "$LOG_FILE" 2>/dev/null || true

	log INFO "Stack purged (including ${HOMEDIR} data dirs)."
}

usage() {
	cat << EOF
Local Apple Studio launcher v5.1.0

  Backend  (${SERVICE_ACCOUNT} / Metal)     →  ${BACKEND_URL}
  Frontend (login user / Docker)        →  ${FRONTEND_URL}

Usage: $0 <command>

  --deploy              Create ${SERVICE_ACCOUNT}, venv, build/create frontend container
  --start               Start backend + frontend (deploys first if needed)
  --stop                Stop both
  --restart             Stop then start
  --status              Health of backend + frontend
  --logs                Tail backend + frontend logs
  --start-backend       Backend only
  --stop-backend        Backend only
  --start-frontend      Frontend container only
  --stop-frontend       Frontend container only
  --import-model [ZIP]  Finder: pick a FLUX snapshot zip (or pass a path)
  --download-model [HF_TOKEN]
                        Fetch ${MODEL_REPO} from Hugging Face into ${MODEL_DIR}
                        Token is used for this run only — never written to ${SERVICE_ACCOUNT} .bashrc
  --export-model [PATH] Finder: choose where to save the model zip (or pass a path)
  --import-loras [ZIP]  Finder: pick a LoRA zip (or pass a path)
  --uninstall           Purge service account, ${HOMEDIR} (incl. data), container, and image
  -h, --help            This help

Backend service account: ${SERVICE_ACCOUNT}  ${HOMEDIR}
Host data: ${HOMEDIR}/{lora,models}  (uploads/outputs are tmpfs inside the frontend container)
Backend jail: sandbox-exec ${SANDBOX_PROFILE}
Frontend jail: --read-only --cap-drop ALL --network ${FRONTEND_NETWORK} (no masquerade)
EOF
}

main() {
	setup_logging

	case "${1:-}" in
		--deploy|--start|--stop|--restart|--start-backend|--stop-backend|--start-frontend|--stop-frontend|--import-model|--download-model|--export-model|--import-loras|--uninstall)
			acquire_lock
			;;
	esac

	case "${1:-}" in
		--deploy) deploy_all ;;
		--start) start_all ;;
		--stop) stop_all ;;
		--restart) stop_all; start_all ;;
		--status) status_all ;;
		--logs) logs_all ;;
		--start-backend) start_backend ;;
		--stop-backend) stop_backend ;;
		--start-frontend) start_frontend ;;
		--stop-frontend) stop_frontend ;;
		--import-model) import_model "${2:-}" ;;
		--download-model) download_model "${2:-}" ;;
		--export-model) export_model "${2:-}" ;;
		--import-loras) import_loras "${2:-}" ;;
		--uninstall) uninstall_all ;;
		-h|--help|"") usage ;;
		*)
			log ERROR "Unknown command: $1"
			usage
			exit 1
			;;
	esac
}

main "$@"
