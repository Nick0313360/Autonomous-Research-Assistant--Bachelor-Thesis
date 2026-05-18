// Flow                          // TypeScript
type T = {| x: number |}        → type T = { x: number }  // exact objects become default
?string                          → string | null | undefined
$ReadOnly<T>                     → Readonly<T>
$Exact<T>                        → T  // (TypeScript objects are exact by default in most contexts)
$Keys<T>                         → keyof T
$Values<T>                       → T[keyof T]
$ElementType<T, K>               → T[K]
$Call<F>                          → ReturnType<F>
// @flow                          → (remove)
/* :: */                          → (remove)
