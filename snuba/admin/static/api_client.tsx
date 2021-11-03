type SystemQuery = {
    description: string | null,
    name: string,
    sql: string,
}

interface Client {
  getConfigs: () => Promise<Map<string, string | number>>;
  getQueries: () => Promise<SystemQuery[]>;
}

function Client() {
  const baseUrl = "/";

  return {
    getConfigs: async () => {
      const url = baseUrl + "configs";
      return fetch(url).then((resp) => resp.json());
    },
    getQueries: async() => {
      const url = baseUrl + "clickhouse_queries";
      return fetch(url).then((resp) => resp.json());

    }
  };
}

export default Client;
