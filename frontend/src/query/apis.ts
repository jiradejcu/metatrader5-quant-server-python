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

export async function toggleGridBot(API_BASE_URL: string): Promise<Response> {
  const url = `${API_BASE_URL}/toggle-grid-bot`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to toggle grid bot: ${response.statusText}`);
  }

  return response;
}

export class ApiError extends Error {
  messages: string[];
  constructor(messages: string[]) {
    super(messages.join('; '));
    this.messages = messages;
  }
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
    let messages: string[];
    try {
      const body = await response.json();
      if (Array.isArray(body.errors) && body.errors.length > 0) {
        messages = body.errors;
      } else if (typeof body.message === 'string') {
        messages = [body.message];
      } else if (Array.isArray(body.detail)) {
        messages = body.detail.map((e: any) => e.msg ?? JSON.stringify(e));
      } else if (typeof body.detail === 'string') {
        messages = [body.detail];
      } else {
        messages = [response.statusText];
      }
    } catch {
      messages = [response.statusText];
    }
    throw new ApiError(messages);
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

export type TimeRange = { start: string; end: string };
export type TradingSessions = Record<string, TimeRange[]>;

export async function getTradingSessions(API_BASE_URL: string): Promise<TradingSessions> {
  const url = `${API_BASE_URL}/trading-sessions`;
  const response = await fetch(url, { method: 'GET' });
  if (!response.ok) throw new Error(`Failed to get trading sessions: ${response.statusText}`);
  const body = await response.json();
  return body.data as TradingSessions;
}

export async function setTradingSessions(API_BASE_URL: string, sessions: TradingSessions): Promise<void> {
  const url = `${API_BASE_URL}/trading-sessions`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sessions),
  });
  if (!response.ok) {
    let messages: string[];
    try {
      const body = await response.json();
      messages = typeof body.message === 'string' ? [body.message] : [response.statusText];
    } catch {
      messages = [response.statusText];
    }
    throw new ApiError(messages);
  }
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