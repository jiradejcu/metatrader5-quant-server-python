import type { SettingGridProps } from "../interfaces/setting-grid.interface";

export async function pauseDisplay(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/pause-position-sync`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to pause display: ${response.statusText}`);
  }

  return response;
}

export async function pauseGridBot(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/pause-grid-bot`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to pause grid bot: ${response.statusText}`);
  }

  return response;
}

export async function setupGridParameters(API_BASE_URL: string, parameters: SettingGridProps): Promise<Response> {
  const url = `${API_BASE_URL}/set-grid-channel`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(parameters),
  });
  
  if (!response.ok) {
    throw new Error(`Failed to set grid parameters: ${response.statusText}`);
  }

  return response;
}

export async function stopBotService(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/stop-quant`
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    }
  })

  if (!response.ok) {
    throw new Error(`Failed to stop bot service: ${response.statusText}`)
  }

  return response
}

export async function restartBotService(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/restart`
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
    "container": "django"
    })
  })

  if (!response.ok) {
    throw new Error(`Failed to stop bot service: ${response.statusText}`)
  }

  return response
}

export async function getBotContainerStatus(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/get-django-status`
  const response = await fetch(url, {
    method: 'GET'
  })

  if (!response.ok) {
    throw new Error(`Failed to get bot container status: ${response.statusText}`)
  }

  return response
}

export async function getArbitrageSummary(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/get-arbitrage-summary`
  const response = await fetch(url, {
    method: 'GET',
  })

  if (!response.ok) {
    throw new Error(`Failed to get summary service: ${response.statusText}`)
  }

  return response
}

export async function getActiveUserInfo(API_BASE_URL: string): Promise<Response> {
  const url =`${API_BASE_URL}/user-info`
  const response = await fetch(url, {
    method: 'GET'
  })

  if (!response.ok) {
    throw new Error(`Failed to get active user service: ${response.statusText}`)
  }

  return response
}