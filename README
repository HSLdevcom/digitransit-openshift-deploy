# Installation

Install the script and requirements globally::

    pip install -e .

Install to $HOME::

    pip install --user -e .

Run (from project root containing data folders)::

    dt_os_menu

# Creating OpenShift project

First, you should create an openshift project and select that by: `oc project`

# Configuring environment

All configuration variables should be stored in OpenShift secrets:
https://docs.openshift.com/enterprise/3.1/dev_guide/secrets.html

Secrets can be created:

 - oc create secret generic {name} --from-literal=key=val

## HSL Map Server

Configure variables for: `fontstack`

- oc create secret generic fontstack --from-literal=fontstackpassword=INSERT

## Digitransit-ui

Configure variables for: `sentry`, `piwik`, `api_url`

- oc create secret generic sentry --from-literal=sentrydsn=https://SENTRY_USER@app.getsentry.com/SENTRY_ID --from-literal=sentrysecretdsn=https://SENTRY_USER:SENTRY_PW@app.getsentry.com/SENTRY_ID
- oc create secret generic piwik --from-literal=id-hsl=INSERT --from-literal=id-default=INSERT --from-literal=address=//piwik.digitransit.fi/piwik.php
- oc create secret generic api-url --from-literal=api-url=INSERT
- oc create secret generic map-url --from-literal=map-url=INSERT

Examples for piwik and api_url:

**DEV**:

- oc create secret generic piwik --from-literal=id-hsl=5 --from-literal=id-default=7 --from-literal=address=//piwik.digitransit.fi/piwik.php
- oc create secret generic api-url --from-literal=api-url=http://dev-api.digitransit.fi
- oc create secret generic map-url --from-literal=map-url=http://{s}-dev-api.digitransit.fi

**TEST**:

- oc create secret generic piwik --from-literal=id-hsl=4 --from-literal=id-default=6 --from-literal=address=//piwik.digitransit.fi/piwik.php
- oc create secret generic api-url --from-literal=api-url=http://api.digitransit.fi
- oc create secret generic map-url --from-literal=map-url=http://{s}-api.digitransit.fi

# Create Deployment configs and services

Using dt_os_menu, run `recreate dc all` and after that `recreate svc all`

# Deploy new version of image

Using dt_os_menu, run `deploy_image {name}`

# Configuring OpenShift routes

Routes should be configured in three steps:

1. DEV ENV: using dt_os_menu run `recreate route-dev digitransit-proxy`

2. TEST ENV: using dt_os_menu run `recreate route-test digitransit-proxy`

3. Configure correct TLS keys manually for both projects using OpenShift tools

# Listing all variables in secrets

Using dt_os_menu, run `secrets clear`
