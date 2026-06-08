// src/api/graphql/fragments/UserFragment.ts
export const USER_FRAGMENT = gql`
  fragment UserFields on User {
    id
    email
    name
    avatarUrl
  }
`;

export const USER_WITH_POSTS_FRAGMENT = gql`
  ${USER_FRAGMENT}
  fragment UserWithPosts on User {
    ...UserFields
    posts(first: $postsLimit) {
      edges { node { id title createdAt } }
      pageInfo { hasNextPage endCursor }
    }
  }
`;
