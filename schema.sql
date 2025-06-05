-- Update patients table to include version tracking
ALTER TABLE patients
ADD COLUMN last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
ADD COLUMN version INT DEFAULT 1,
ADD COLUMN status ENUM('active', 'inactive', 'archived') DEFAULT 'active';

-- Add indexes for better performance
CREATE INDEX idx_patient_email ON patients(email);
CREATE INDEX idx_patient_status ON patients(status);
CREATE INDEX idx_patient_last_updated ON patients(last_updated);

-- Add version tracking to related tables
ALTER TABLE symptoms
ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE medications
ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE allergies
ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

-- Add audit trail table
CREATE TABLE audit_trail (
    audit_id INT PRIMARY KEY AUTO_INCREMENT,
    patient_id INT,
    table_name VARCHAR(50),
    operation_type ENUM('INSERT', 'UPDATE', 'DELETE'),
    old_value JSON,
    new_value JSON,
    operation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    operation_id VARCHAR(36),
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- Add operation_recovery table
CREATE TABLE operation_recovery (
    operation_id VARCHAR(36) PRIMARY KEY,
    patient_id INT,
    operation_type VARCHAR(50),
    operation_state JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    status ENUM('pending', 'completed', 'failed', 'recovered') DEFAULT 'pending',
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
); 
