use crate::types::{PersonalCreditInput, PersonalCreditOutput};

pub fn recover(_input: PersonalCreditInput) -> PersonalCreditOutput {
    PersonalCreditOutput {
        schema_version: 1,
        tables: Vec::new(),
        diagnostics: Vec::new(),
    }
}
