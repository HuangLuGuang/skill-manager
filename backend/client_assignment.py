def device_user(client, credential=None):
    if client.device_user:
        return client.device_user
    if credential:
        return credential.device_user or credential.created_by or client.registered_by
    return client.registered_by
