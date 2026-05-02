export const useAllBots = () => {
    // n Bots
    const botUrl1 = import.meta.env.VITE_API_BASE_URL_1;
    const botUrl2 = import.meta.env.VITE_API_BASE_URL_2;
    const botUrl3 = import.meta.env.VITE_API_BASE_URL_3
    const botUrlDev = import.meta.env.VITE_API_BASE_URL_DEV

    return {
        botUrl1,
        botUrl2,
        botUrl3,
        botUrlDev
    }
}