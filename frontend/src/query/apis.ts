const API_BASE_URL = 'https://mt5-django.vatanutanon.me/displays';

/**
 * Executes the POST request to pause the display.
 * @returns {Promise<Response>} The API response.
 */
export async function pauseDisplay(): Promise<Response> {
  const url = `${API_BASE_URL}/pause/`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // 'Authorization': `Bearer ${yourAccessToken}`,
    },
    // body: JSON.stringify({ /* data if needed */ }),
  });

  if (!response.ok) {
    // โยน Error หากสถานะ HTTP ไม่ใช่ 2xx
    throw new Error(`Failed to pause display: ${response.statusText}`);
  }

  return response;
}

// todo: add get data from redis cache

// todo: add stop container django (circuit breaker service)