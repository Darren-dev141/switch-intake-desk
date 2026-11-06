#!/usr/bin/env bash
# Run Mattermost natively (equivalent of the standalone stack's `mattermost` service).
RT="$HOME/workspace/flip-the-switch/runtime"
source "$RT/stack-env.sh"
MMROOT=/var/lib/switch-stack/mmroot/mattermost
mkdir -p /var/lib/switch-stack/mmdata
export MM_SQLSETTINGS_DRIVERNAME=postgres
export MM_SQLSETTINGS_DATASOURCE="postgres://${DB_OWNER_USER}:${DB_OWNER_PASSWORD}@127.0.0.1:5432/mattermost?sslmode=disable"
export MM_SERVICESETTINGS_SITEURL="http://localhost:8065"
export MM_SERVICESETTINGS_ENABLELOCALMODE="true"
export MM_SERVICESETTINGS_ENABLEBOTACCOUNTCREATION="true"
export MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS="true"
# switch-core's callback listener is on this host's 8081 in the native layout.
export MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS="127.0.0.1 localhost"
export MM_TEAMSETTINGS_ENABLEOPENSERVER="true"
export MM_TEAMSETTINGS_TEAMMATENAMEDISPLAY="full_name"
export MM_SERVICESETTINGS_ENABLEONBOARDINGFLOW="false"
export MM_DISPLAYSETTINGS_CUSTOMURLSCHEMES="switchdash"
export MM_LOGSETTINGS_ENABLEDIAGNOSTICS="false"
export MM_LOGSETTINGS_ENABLESENTRY="false"
export MM_SERVICESETTINGS_ENABLESECURITYFIXALERT="false"
export MM_ANNOUNCEMENTSETTINGS_ADMINNOTICESENABLED="false"
export MM_ANNOUNCEMENTSETTINGS_USERNOTICESENABLED="false"
export MM_PLUGINSETTINGS_ENABLEREMOTEMARKETPLACE="false"
export MM_PLUGINSETTINGS_PLUGINSTATES='{"mattermost-ai":{"Enable":false},"com.mattermost.calls":{"Enable":false}}'
export MM_FILESETTINGS_DIRECTORY="/var/lib/switch-stack/mmdata"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export no_proxy="127.0.0.1,localhost" NO_PROXY="127.0.0.1,localhost"
cd "$MMROOT"
exec setpriv --reuid 2000 --regid 2000 --clear-groups \
  "$MMROOT/bin/mattermost" --config /var/lib/switch-stack/mm-config.json >> "$RT/mm.log" 2>&1
