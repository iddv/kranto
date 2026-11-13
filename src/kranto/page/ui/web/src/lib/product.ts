// The product's name, in one place for the page (the server's is src/kranto/product.py). Sentences
// take the name from here; anything typed (the command) takes COMMAND.
export const PRODUCT = "Kranto";
/** the name where it opens a sentence: as it is written */
export const Product = PRODUCT;
/** the possessive: "Kranto's folder" */
export const PRODUCTS = PRODUCT + (PRODUCT.endsWith("s") ? "'" : "'s");
/** the command a person types: `kranto update` */
export const COMMAND = "kranto";
