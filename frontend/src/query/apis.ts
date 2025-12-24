const API_BASE_URL = 'https://arbitrage-control.vatanutanon.me';

export async function pauseDisplay(): Promise<Response> {
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

// export async function startBotService(): Promise<Response> {
//   const url = `${API_BASE_URL}/start-quant/`
//   const response = await fetch(url, {
//     method: 'POST',
//     headers: {
//       'Content-Type': 'application/json'
//     }
//   })

//   if (!response.ok) {
//     throw new Error(`Failed to start bot service: ${response.statusText}`)
//   }

//   return response
// }
// // todo: add stop container django (circuit breaker service)
// export async function stopBotService(): Promise<Response> {
//   const url = `${API_BASE_URL}/stop-quant/`
//   const response = await fetch(url, {
//     method: 'POST',
//     headers: {
//       'Content-Type': 'application/json'
//     }
//   })

//   if (!response.ok) {
//     throw new Error(`Failed to stop bot service: ${response.statusText}`)
//   }

//   return response
// }
// todo: add get data from redis cache
export async function getArbitrageSummary(): Promise<Response> {
  const url = `${API_BASE_URL}/get-arbitrage-summary`
  const response = await fetch(url, {
    method: 'GET',
  })

  if (!response.ok) {
    throw new Error(`Failed to get summary service: ${response.statusText}`)
  }

  return response
}