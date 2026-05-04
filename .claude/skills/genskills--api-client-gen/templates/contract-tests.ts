// src/api/testing/contracts.ts
import { PactV4, SpecificationVersion } from "@pact-foundation/pact";

export function createUserContractTests() {
  const provider = new PactV4({
    consumer: "frontend",
    provider: "user-service",
    spec: SpecificationVersion.SPECIFICATION_VERSION_V4,
  });

  describe("User API Contract", () => {
    it("should return a user by ID", async () => {
      await provider
        .addInteraction()
        .given("a user with ID user-123 exists")
        .uponReceiving("a request to get user user-123")
        .withRequest("GET", "/api/users/user-123")
        .willRespondWith(200, (builder) => {
          builder.jsonBody({
            status: "success",
            data: {
              id: "user-123",
              email: provider.string("user@example.com"),
              name: provider.string("Jane Doe"),
            },
          });
        })
        .executeTest(async (mockServer) => {
          const client = new ApiClient({ baseUrl: mockServer.url });
          const result = await client.users.get(UserId("user-123"));
          expect(result.status).toBe("success");
        });
    });
  });
}
