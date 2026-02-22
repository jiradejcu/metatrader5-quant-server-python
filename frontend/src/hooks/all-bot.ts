export const useAllBots = () => {
    // n Bots
    const botUrl = import.meta.env.VITE_API_BASE_URL;
    const botUrl2 = import.meta.env.VITE_API_BASE_URL_2;
    const botUrl3 = import.meta.env.VITE_API_BASE_URL_3
    const botUrlDev = import.meta.env.VITE_API_BASE_URL_DEV

    return {
        botUrl,
        botUrl2,
        botUrl3,
        botUrlDev
    }
}